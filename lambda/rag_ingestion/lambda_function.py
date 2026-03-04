"""
RAG Ingestion Lambda Function
Ingests documents from S3, chunks them, and generates embeddings
"""
import json
import os
import uuid
from typing import Dict, Any, List
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMBEDDINGS_TABLE_NAME = os.environ['EMBEDDINGS_TABLE_NAME']
TITAN_EMBEDDINGS_MODEL_ID = "amazon.titan-embed-text-v1"

embeddings_table = dynamodb.Table(EMBEDDINGS_TABLE_NAME)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for RAG ingestion

    Args:
        event: S3 event or direct invocation with bucket/key
        context: Lambda context

    Returns:
        Dict with ingestion results
    """
    try:
        # Extract bucket and key from event
        if 'Records' in event:
            # S3 event trigger
            record = event['Records'][0]
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
        else:
            # Direct invocation
            bucket = event.get('bucket')
            key = event.get('key')

        if not bucket or not key:
            raise ValueError("Missing bucket or key in event")

        print(f"Processing document: s3://{bucket}/{key}")

        # Get document from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')

        # Determine document type
        doc_type = determine_doc_type(key)

        # Chunk document
        chunks = chunk_document(content, chunk_size=500, overlap=50)
        print(f"Created {len(chunks)} chunks")

        # Process each chunk
        ingested_count = 0
        for i, chunk in enumerate(chunks):
            try:
                # Generate embedding
                embedding = generate_embedding(chunk)

                # Store in DynamoDB
                doc_id = f"{key.replace('/', '_')}_{i}"
                store_embedding(doc_id, chunk, embedding, doc_type, key, i)

                ingested_count += 1

            except Exception as e:
                print(f"Error processing chunk {i}: {str(e)}")
                continue

        return {
            'statusCode': 200,
            'document': key,
            'doc_type': doc_type,
            'chunks_processed': ingested_count,
            'total_chunks': len(chunks)
        }

    except ClientError as e:
        print(f"AWS Error: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e)
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e)
        }


def determine_doc_type(key: str) -> str:
    """Determine document type from S3 key"""
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


def chunk_document(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Chunk document into overlapping segments

    Args:
        text: Input text
        chunk_size: Target chunk size in tokens (approximated by words)
        overlap: Overlap size in tokens

    Returns:
        List of text chunks
    """
    # Split into words (rough token approximation)
    words = text.split()

    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunks.append(' '.join(chunk_words))

        # Move to next chunk with overlap
        start = end - overlap
        if start >= len(words):
            break

    return chunks


def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding using Amazon Titan Embeddings

    Args:
        text: Input text

    Returns:
        List of floats representing the embedding
    """
    try:
        # Truncate if too long
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars]

        request_body = json.dumps({
            "inputText": text
        })

        response = bedrock_runtime.invoke_model(
            modelId=TITAN_EMBEDDINGS_MODEL_ID,
            body=request_body,
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())
        embedding = response_body.get('embedding')

        return embedding

    except Exception as e:
        print(f"Error generating embedding: {str(e)}")
        raise


def store_embedding(
    doc_id: str,
    content: str,
    embedding: List[float],
    doc_type: str,
    source_key: str,
    chunk_index: int
) -> None:
    """
    Store embedding and metadata in DynamoDB

    Args:
        doc_id: Unique document ID
        content: Chunk content
        embedding: Embedding vector
        doc_type: Document type
        source_key: S3 key of source document
        chunk_index: Index of chunk in document
    """
    try:
        # Convert embedding list to JSON string for DynamoDB storage
        # DynamoDB doesn't support lists of floats natively
        embedding_json = json.dumps(embedding)

        item = {
            'doc_id': doc_id,
            'doc_type': doc_type,
            'content': content[:1000],  # Store first 1000 chars
            'embedding': embedding_json,  # Store as JSON string
            'metadata': {
                'source_key': source_key,
                'chunk_index': chunk_index,
                'content_length': len(content),
                'embedding_dim': len(embedding)
            },
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }

        embeddings_table.put_item(Item=item)
        print(f"✓ Stored embedding for {doc_id}")

    except Exception as e:
        print(f"Error storing embedding: {str(e)}")
        raise
