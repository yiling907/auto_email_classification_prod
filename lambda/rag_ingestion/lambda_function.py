"""
RAG Ingestion Lambda Function
Ingests documents from S3, chunks them, and generates embeddings
"""
import hashlib
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, Any, List, Tuple
from urllib.parse import unquote_plus
import boto3
from botocore.exceptions import ClientError

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

# Initialize AWS clients
s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMBEDDINGS_TABLE_NAME = os.environ['EMBEDDINGS_TABLE_NAME']
TITAN_EMBEDDINGS_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Chunking config (per CLAUDE.md spec: 500 tokens / 50 overlap)
CHUNK_SIZE = 500    # words
OVERLAP = 50        # words
MIN_CHUNK_WORDS = 20  # skip tiny/garbage chunks

# Parallel Bedrock embedding calls
EMBED_WORKERS = 8

embeddings_table = dynamodb.Table(EMBEDDINGS_TABLE_NAME)

# Sentence boundary: split after . ! ? followed by whitespace
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        if 'Records' in event:
            record = event['Records'][0]
            bucket = record['s3']['bucket']['name']
            key = unquote_plus(record['s3']['object']['key'])
        else:
            bucket = event.get('bucket')
            key = event.get('key')

        if not bucket or not key:
            raise ValueError("Missing bucket or key in event")

        print(f"Processing document: s3://{bucket}/{key}")

        response = s3_client.get_object(Bucket=bucket, Key=key)
        raw_bytes = response['Body'].read()

        if key.lower().endswith('.pdf'):
            if not PYPDF_AVAILABLE:
                raise RuntimeError("pypdf is not installed; cannot process PDF files")
            reader = PdfReader(io.BytesIO(raw_bytes))
            content = '\n'.join(page.extract_text() or '' for page in reader.pages)
        else:
            content = raw_bytes.decode('utf-8')

        doc_type = determine_doc_type(key)
        chunks = chunk_document(content)
        print(f"Created {len(chunks)} chunks")

        # Generate all embeddings in parallel
        embedded = embed_chunks_parallel(chunks, key, doc_type)

        # Batch-write to DynamoDB (25 items per batch call)
        ingested_count = batch_store_embeddings(embedded)

        return {
            'statusCode': 200,
            'document': key,
            'doc_type': doc_type,
            'chunks_processed': ingested_count,
            'total_chunks': len(chunks)
        }

    except ClientError as e:
        print(f"AWS Error: {str(e)}")
        return {'statusCode': 500, 'error': str(e)}
    except Exception as e:
        print(f"Error: {str(e)}")
        return {'statusCode': 500, 'error': str(e)}


def determine_doc_type(key: str) -> str:
    """Determine document type from S3 key."""
    key_lower = key.lower()
    if 'policy' in key_lower:
        return 'policy'
    elif 'claim' in key_lower:
        return 'claims_guideline'
    elif 'compliance' in key_lower or 'disclaimer' in key_lower:
        return 'compliance'
    elif 'faq' in key_lower:
        return 'faq'
    elif 'template' in key_lower:
        return 'template'
    else:
        return 'general'


def chunk_document(text: str) -> List[str]:
    """
    Sentence-aware chunking with deduplication and min-size filter.

    Splits on sentence boundaries so chunks don't break mid-sentence.
    Keeps a OVERLAP-word tail from the previous chunk to preserve context.
    Deduplicates identical chunks that appear across multiple source files.
    """
    sentences = _SENTENCE_END.split(text.strip())

    chunks: List[str] = []
    seen_hashes: set = set()
    current_words: List[str] = []

    for sentence in sentences:
        sentence_words = sentence.split()
        if not sentence_words:
            continue

        # Sentence is itself longer than the budget — hard-split it
        while len(sentence_words) > CHUNK_SIZE:
            space = CHUNK_SIZE - len(current_words)
            current_words.extend(sentence_words[:space])
            _maybe_add_chunk(' '.join(current_words), chunks, seen_hashes)
            current_words = current_words[-OVERLAP:]
            sentence_words = sentence_words[space:]

        # Flush current buffer if this sentence would overflow
        if current_words and len(current_words) + len(sentence_words) > CHUNK_SIZE:
            _maybe_add_chunk(' '.join(current_words), chunks, seen_hashes)
            current_words = current_words[-OVERLAP:]

        current_words.extend(sentence_words)

    if current_words:
        _maybe_add_chunk(' '.join(current_words), chunks, seen_hashes)

    return chunks


def _maybe_add_chunk(text: str, chunks: List[str], seen_hashes: set) -> None:
    """Add chunk only if it meets the minimum word count and is not a duplicate."""
    if len(text.split()) < MIN_CHUNK_WORDS:
        return
    h = hashlib.md5(text.encode()).hexdigest()
    if h in seen_hashes:
        return
    seen_hashes.add(h)
    chunks.append(text)


def embed_chunks_parallel(
    chunks: List[str],
    source_key: str,
    doc_type: str,
) -> List[Tuple[str, str, List[float], str, str, int]]:
    """
    Generate embeddings for all chunks concurrently.
    Returns list of (doc_id, content, embedding, doc_type, source_key, chunk_index).
    """
    def embed_one(args: Tuple[int, str]):
        i, chunk = args
        doc_id = f"{source_key.replace('/', '_')}_{i}"
        embedding = generate_embedding(chunk)
        return (doc_id, chunk, embedding, doc_type, source_key, i)

    results = []
    with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as executor:
        futures = {executor.submit(embed_one, (i, chunk)): i for i, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                print(f"Error embedding chunk {i}: {e}")

    return results


def generate_embedding(text: str) -> List[float]:
    """Generate a 1024-dim normalized embedding via Amazon Titan Embeddings V2."""
    if len(text) > 8000:
        text = text[:8000]

    response = bedrock_runtime.invoke_model(
        modelId=TITAN_EMBEDDINGS_MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
        contentType='application/json',
        accept='application/json',
    )
    return json.loads(response['body'].read())['embedding']


def batch_store_embeddings(
    results: List[Tuple[str, str, List[float], str, str, int]]
) -> int:
    """
    Write embeddings to DynamoDB using batch_writer (auto-batches in groups of 25).
    Returns number of items written.
    """
    now = datetime.utcnow().isoformat() + 'Z'
    ingested_count = 0

    with embeddings_table.batch_writer() as batch:
        for doc_id, content, embedding, doc_type, source_key, chunk_index in results:
            batch.put_item(Item={
                'doc_id': doc_id,
                'doc_type': doc_type,
                'content': content,
                'embedding': json.dumps(embedding),
                'metadata': {
                    'source_key': source_key,
                    'chunk_index': chunk_index,
                    'content_length': len(content),
                    'embedding_dim': len(embedding),
                },
                'timestamp': now,
            })
            ingested_count += 1

    print(f"Batch-stored {ingested_count} embeddings")
    return ingested_count
