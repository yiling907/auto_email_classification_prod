"""
RAG Retrieval Lambda Function
Retrieves relevant knowledge base snippets using semantic similarity
"""
import json
import os
from typing import Dict, Any, List
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMBEDDINGS_TABLE_NAME = os.environ['EMBEDDINGS_TABLE_NAME']
TITAN_EMBEDDINGS_MODEL_ID = "amazon.titan-embed-text-v1"

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

        print(f"Retrieving knowledge for email text (length: {len(email_text)})")

        # Generate embedding for email text
        email_embedding = generate_embedding(email_text)

        # Retrieve top-K similar documents
        top_k = event.get('top_k', 3)
        similar_docs = retrieve_similar_documents(email_embedding, top_k)

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

        print(f"Generated embedding with dimension: {len(embedding)}")
        return embedding

    except Exception as e:
        print(f"Error generating embedding: {str(e)}")
        raise


def retrieve_similar_documents(query_embedding: List[float], top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Retrieve similar documents using cosine similarity

    Args:
        query_embedding: Query embedding vector
        top_k: Number of top documents to retrieve

    Returns:
        List of similar documents with scores
    """
    try:
        # Scan all documents from DynamoDB
        # Note: In production, use a proper vector database (Pinecone, Weaviate, etc.)
        # or AWS OpenSearch for efficient similarity search
        response = embeddings_table.scan()
        documents = response.get('Items', [])

        if not documents:
            print("No documents found in knowledge base")
            return []

        # Calculate similarity scores
        scored_docs = []
        for doc in documents:
            if 'embedding' in doc:
                try:
                    # Parse embedding from JSON string back to list of floats
                    doc_embedding_str = doc['embedding']
                    if isinstance(doc_embedding_str, str):
                        doc_embedding = json.loads(doc_embedding_str)
                    else:
                        # Already a list (shouldn't happen with new code, but handle for backwards compat)
                        doc_embedding = doc_embedding_str

                    similarity = cosine_similarity(query_embedding, doc_embedding)
                    scored_docs.append({
                        'doc_id': doc.get('doc_id'),
                        'doc_type': doc.get('doc_type', 'unknown'),
                        'content': doc.get('content', ''),
                        'similarity_score': similarity,
                        'metadata': doc.get('metadata', {})
                    })
                except Exception as e:
                    print(f"Error processing document {doc.get('doc_id')}: {str(e)}")
                    continue

        # Sort by similarity and return top-K
        scored_docs.sort(key=lambda x: x['similarity_score'], reverse=True)
        top_docs = scored_docs[:top_k]

        print(f"Retrieved {len(top_docs)} documents")
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
