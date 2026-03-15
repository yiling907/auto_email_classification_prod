"""
RAG Retrieval Lambda Function
Retrieves relevant knowledge base snippets using semantic similarity
"""
import json
import os
import re
from typing import Dict, Any, List
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMBEDDINGS_TABLE_NAME = os.environ['EMBEDDINGS_TABLE_NAME']
TITAN_EMBEDDINGS_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Minimum similarity to include a doc in results
SIMILARITY_THRESHOLD = 0.30

_GREETING  = re.compile(r'^(dear\s+\S.*?[,\n]|hi\s*\S*.*?[,\n]|hello\s*\S*.*?[,\n])', re.I)
_SIGN_OFF  = re.compile(r'(kind regards.*|best regards.*|yours sincerely.*|thank\s+you.*|thanks.*)$', re.I | re.S)

embeddings_table = dynamodb.Table(EMBEDDINGS_TABLE_NAME)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for RAG retrieval

    Args:
        event: Contains email_text for embedding generation
        context: Lambda context

    Returns:
        Dict with top-K relevant knowledge snippets
    """
    try:
        email_text = event.get('email_text') or event.get('body')

        if not email_text:
            raise ValueError("Missing email_text in event")

        intent = event.get('intent', '')
        query  = preprocess_query(email_text, intent)
        print(f"Retrieving knowledge — raw_len={len(email_text)} query_len={len(query)} intent={intent!r}")

        # Generate embedding for cleaned query
        email_embedding = generate_embedding(query)

        # Retrieve top-K similar documents with hybrid scoring
        top_k = event.get('top_k', 5)
        similar_docs = retrieve_similar_documents(email_embedding, top_k, query)

        return {
            'statusCode': 200,
            'retrieved_documents': similar_docs,
            'num_documents': len(similar_docs)
        }

    except ClientError as e:
        print(f"AWS Error: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e),
            'retrieved_documents': []
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e),
            'retrieved_documents': []
        }


def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding using Amazon Titan Embeddings

    Args:
        text: Input text

    Returns:
        List of floats representing the embedding
    """
    try:
        # Truncate text if too long (Titan has input limits)
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars]

        request_body = json.dumps({
            "inputText": text,
            "dimensions": 1024,
            "normalize": True,
        })

        response = bedrock_runtime.invoke_model(
            modelId=TITAN_EMBEDDINGS_MODEL_ID,
            body=request_body,
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())
        embedding = response_body.get('embedding')

        print(f"Generated embedding with dimension: {len(embedding)}")
        return embedding

    except Exception as e:
        print(f"Error generating embedding: {str(e)}")
        raise


def preprocess_query(email_text: str, intent: str = '') -> str:
    """
    Strip greeting/sign-off noise and prepend intent for sharper embeddings.
    The intent prefix anchors the embedding toward the insurance subdomain.
    """
    text = email_text.strip()
    text = _GREETING.sub('', text).strip()
    text = _SIGN_OFF.sub('', text).strip()
    if intent:
        label = intent.replace('_', ' ')
        text = f"Insurance query about {label}: {text}"
    return text[:8000]


def keyword_score(query: str, document: str) -> float:
    """
    Term-overlap score: fraction of unique query terms (≥3 chars) found in doc.
    Captures exact insurance terminology (e.g. 'excess', 'pre-authorisation')
    that embeddings may conflate with semantically similar but wrong terms.
    """
    query_terms = set(re.findall(r'\b\w{3,}\b', query.lower()))
    if not query_terms:
        return 0.0
    doc_terms = set(re.findall(r'\b\w{3,}\b', document.lower()))
    return len(query_terms & doc_terms) / len(query_terms)


def retrieve_similar_documents(
    query_embedding: List[float],
    top_k: int = 5,
    query_text: str = '',
) -> List[Dict[str, Any]]:
    """
    Hybrid retrieval: semantic (70%) + keyword (30%).
    Fetches top_k*4 candidates by semantic score, filters by SIMILARITY_THRESHOLD,
    re-ranks with the hybrid score, and returns the top_k results.
    """
    try:
        response  = embeddings_table.scan()
        documents = response.get('Items', [])

        if not documents:
            print("No documents found in knowledge base")
            return []

        candidate_limit = max(top_k * 4, 20)
        scored_docs = []

        for doc in documents:
            if 'embedding' not in doc:
                continue
            try:
                raw = doc['embedding']
                doc_embedding = json.loads(raw) if isinstance(raw, str) else raw
                sem_score = cosine_similarity(query_embedding, doc_embedding)
                scored_docs.append((sem_score, doc))
            except Exception as e:
                print(f"Error processing document {doc.get('doc_id')}: {e}")

        # Take top candidates by semantic score before hybrid re-rank
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        candidates = scored_docs[:candidate_limit]

        # Hybrid re-rank: 70% semantic + 30% keyword
        results = []
        for sem_score, doc in candidates:
            if sem_score < SIMILARITY_THRESHOLD:
                continue
            kw = keyword_score(query_text, doc.get('content', '')) if query_text else 0.0
            hybrid = round(0.7 * sem_score + 0.3 * kw, 4)
            results.append({
                'doc_id':           doc.get('doc_id'),
                'doc_type':         doc.get('doc_type', 'unknown'),
                'content':          doc.get('content', ''),
                'similarity_score': hybrid,
                'metadata':         doc.get('metadata', {}),
            })

        results.sort(key=lambda x: x['similarity_score'], reverse=True)
        top_docs = results[:top_k]

        print(f"Retrieved {len(top_docs)}/{len(candidates)} candidates (threshold={SIMILARITY_THRESHOLD})")
        for doc in top_docs:
            print(f"  - {doc['doc_id']}: {doc['similarity_score']:.4f}")

        return top_docs

    except Exception as e:
        print(f"Error retrieving documents: {str(e)}")
        return []


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine similarity score (0-1)
    """
    try:
        # Ensure vectors are same length
        if len(vec1) != len(vec2):
            print(f"Warning: Vector dimension mismatch: {len(vec1)} vs {len(vec2)}")
            return 0.0

        # Calculate dot product
        dot_product = sum(a * b for a, b in zip(vec1, vec2))

        # Calculate magnitudes
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    except Exception as e:
        print(f"Error calculating similarity: {str(e)}")
        return 0.0
