"""
Unit tests for RAG retrieval Lambda function
"""
import json
import sys
import os
from unittest.mock import patch, MagicMock
import pytest

sys.modules.pop('lambda_function', None)  # avoid module-cache collision when run with other lambda tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/rag_retrieval'))
import lambda_function


class TestRAGRetrieval:
    """Test cases for RAG retrieval Lambda"""

    def test_lambda_handler_success(self, lambda_env_vars, dynamodb_tables, lambda_context, sample_rag_document):
        """Test successful document retrieval"""
        # Add test documents to DynamoDB
        table = dynamodb_tables['embeddings']

        # Store embedding as JSON string (as in production)
        doc = sample_rag_document.copy()
        doc['embedding'] = json.dumps(doc['embedding'])
        table.put_item(Item=doc)

        event = {
            'email_text': 'I need help with my insurance claim',
            'top_k': 3
        }

        with patch.object(lambda_function, 'generate_embedding', return_value=[0.1] * 1536):
            result = lambda_function.lambda_handler(event, lambda_context)

            assert result['statusCode'] == 200
            assert 'retrieved_documents' in result
            assert result['num_documents'] >= 0

    def test_lambda_handler_missing_email_text(self, lambda_env_vars, lambda_context):
        """Test handler with missing email text"""
        event = {}

        result = lambda_function.lambda_handler(event, lambda_context)

        assert result['statusCode'] == 500
        assert 'error' in result

    def test_cosine_similarity_identical_vectors(self):
        """Test cosine similarity with identical vectors"""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [1.0, 2.0, 3.0]

        similarity = lambda_function.cosine_similarity(vec1, vec2)

        assert abs(similarity - 1.0) < 0.0001

    def test_cosine_similarity_orthogonal_vectors(self):
        """Test cosine similarity with orthogonal vectors"""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]

        similarity = lambda_function.cosine_similarity(vec1, vec2)

        assert abs(similarity - 0.0) < 0.0001

    def test_cosine_similarity_opposite_vectors(self):
        """Test cosine similarity with opposite vectors"""
        vec1 = [1.0, 1.0, 1.0]
        vec2 = [-1.0, -1.0, -1.0]

        similarity = lambda_function.cosine_similarity(vec1, vec2)

        assert abs(similarity - (-1.0)) < 0.0001

    def test_cosine_similarity_mismatched_dimensions(self):
        """Test cosine similarity with mismatched vector dimensions"""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [1.0, 2.0]

        similarity = lambda_function.cosine_similarity(vec1, vec2)

        assert similarity == 0.0

    def test_cosine_similarity_zero_magnitude(self):
        """Test cosine similarity with zero magnitude vector"""
        vec1 = [0.0, 0.0, 0.0]
        vec2 = [1.0, 2.0, 3.0]

        similarity = lambda_function.cosine_similarity(vec1, vec2)

        assert similarity == 0.0

    def test_retrieve_similar_documents_ranking(self, lambda_env_vars, dynamodb_tables):
        """Test that documents are ranked by cosine similarity"""
        table = dynamodb_tables['embeddings']

        # Use directionally distinct embeddings so cosine similarities are clearly ordered.
        # query = [1, 0, 0, ...]
        # doc_0: [0, 1, 0, ...] → cos = 0.0  (orthogonal)
        # doc_1: [1, 1, 0, ...] → cos ≈ 0.707 (45 degrees)
        # doc_2: [1, 0, 0, ...] → cos = 1.0  (identical direction)
        dim = 1536
        embeddings = {
            'doc_0': [0.0, 1.0] + [0.0] * (dim - 2),
            'doc_1': [1.0, 1.0] + [0.0] * (dim - 2),
            'doc_2': [1.0, 0.0] + [0.0] * (dim - 2),
        }
        for doc_id, emb in embeddings.items():
            table.put_item(Item={
                'doc_id': doc_id,
                'doc_type': 'policy',
                'content': f'Content for {doc_id}',
                'embedding': json.dumps(emb),
                'metadata': {},
            })

        # Query pointing along dim-0 → doc_2 should be most similar
        query_embedding = [1.0, 0.0] + [0.0] * (dim - 2)
        results = lambda_function.retrieve_similar_documents(query_embedding, top_k=3)

        assert len(results) <= 3
        if len(results) > 0:
            assert results[0]['doc_id'] == 'doc_2'

    def test_retrieve_similar_documents_top_k(self, lambda_env_vars, dynamodb_tables):
        """Test that only top_k documents are returned"""
        table = dynamodb_tables['embeddings']

        # Add 10 documents
        for i in range(10):
            doc = {
                'doc_id': f'doc_{i}',
                'doc_type': 'policy',
                'content': f'Document {i}',
                'embedding': json.dumps([float(i) * 0.1] * 1536),
                'metadata': {}
            }
            table.put_item(Item=doc)

        query_embedding = [0.5] * 1536

        results = lambda_function.retrieve_similar_documents(query_embedding, top_k=3)

        # Should return exactly 3 documents
        assert len(results) == 3

    def test_retrieve_similar_documents_empty_database(self, lambda_env_vars, dynamodb_tables):
        """Test retrieval with empty embeddings table"""
        query_embedding = [0.1] * 1536

        results = lambda_function.retrieve_similar_documents(query_embedding, top_k=3)

        assert len(results) == 0

    def test_retrieve_similar_documents_metadata_preserved(self, lambda_env_vars, dynamodb_tables):
        """Test that document metadata is preserved in results"""
        table = dynamodb_tables['embeddings']

        doc = {
            'doc_id': 'test_doc',
            'doc_type': 'policy',
            'content': 'Test content',
            'embedding': json.dumps([0.1] * 1536),
            'metadata': {
                'source_key': 'policies/test.txt',
                'chunk_index': 0
            }
        }
        table.put_item(Item=doc)

        query_embedding = [0.1] * 1536

        results = lambda_function.retrieve_similar_documents(query_embedding, top_k=1)

        assert len(results) == 1
        assert results[0]['doc_id'] == 'test_doc'
        assert results[0]['doc_type'] == 'policy'
        assert results[0]['content'] == 'Test content'
        assert 'similarity_score' in results[0]
        assert 'metadata' in results[0]

    def test_generate_embedding_truncation(self, lambda_env_vars):
        """Test that long text is truncated before embedding generation"""
        long_text = "x" * 10000  # 10k characters

        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = json.dumps({
            'embedding': [0.1] * 1536
        }).encode('utf-8')

        with patch.object(lambda_function.bedrock_runtime, 'invoke_model', return_value=mock_response) as mock_invoke:
            embedding = lambda_function.generate_embedding(long_text)

            # Verify truncation happened
            call_args = mock_invoke.call_args
            request_body = json.loads(call_args[1]['body'])
            assert len(request_body['inputText']) == 8000


class TestEmbeddingParsing:
    """Test embedding parsing from DynamoDB"""

    def test_parse_json_string_embedding(self, lambda_env_vars, dynamodb_tables):
        """Test parsing embedding stored as JSON string"""
        table = dynamodb_tables['embeddings']

        embedding_list = [0.1, 0.2, 0.3]
        doc = {
            'doc_id': 'test_json',
            'doc_type': 'policy',
            'content': 'Test',
            'embedding': json.dumps(embedding_list),  # Stored as JSON string
            'metadata': {}
        }
        table.put_item(Item=doc)

        query_embedding = [0.15, 0.25, 0.35]
        results = lambda_function.retrieve_similar_documents(query_embedding, top_k=1)

        assert len(results) == 1
        # Should successfully parse and calculate similarity

    def test_handle_corrupted_embedding(self, lambda_env_vars, dynamodb_tables):
        """Test handling of corrupted embedding data"""
        table = dynamodb_tables['embeddings']

        doc = {
            'doc_id': 'corrupted',
            'doc_type': 'policy',
            'content': 'Test',
            'embedding': 'invalid json [[[',  # Corrupted JSON
            'metadata': {}
        }
        table.put_item(Item=doc)

        query_embedding = [0.1] * 1536

        # Should not crash, just skip corrupted document
        results = lambda_function.retrieve_similar_documents(query_embedding, top_k=1)

        # Corrupted doc should be skipped
        assert len(results) == 0
