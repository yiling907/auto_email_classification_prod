"""
Unit tests for RAG ingestion Lambda function
"""
import json
import sys
import os
from unittest.mock import Mock, patch, MagicMock
import pytest

sys.modules.pop('lambda_function', None)  # avoid module-cache collision when run with other lambda tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/rag_ingestion'))
import lambda_function


class TestRAGIngestion:
    """Test cases for RAG ingestion Lambda"""

    def test_lambda_handler_s3_event(self, lambda_env_vars, s3_buckets, dynamodb_tables, lambda_context):
        """Test handler with S3 event trigger"""
        # Put test document in S3
        s3_buckets.put_object(
            Bucket='test-knowledge-base-bucket',
            Key='policies/test_policy.txt',
            Body=b'This is a test insurance policy document.'
        )

        event = {
            'Records': [{
                's3': {
                    'bucket': {'name': 'test-knowledge-base-bucket'},
                    'object': {'key': 'policies/test_policy.txt'}
                }
            }]
        }

        with patch.object(lambda_function, 'generate_embedding', return_value=[0.1] * 1536):
            result = lambda_function.lambda_handler(event, lambda_context)

            assert result['statusCode'] == 200
            assert result['document'] == 'policies/test_policy.txt'
            assert result['doc_type'] == 'policy'
            assert result['chunks_processed'] > 0

    def test_lambda_handler_direct_invocation(self, lambda_env_vars, s3_buckets, dynamodb_tables, lambda_context):
        """Test handler with direct invocation (not S3 event)"""
        s3_buckets.put_object(
            Bucket='test-knowledge-base-bucket',
            Key='claims/guideline.txt',
            Body=b'Claims processing guidelines for insurance.'
        )

        event = {
            'bucket': 'test-knowledge-base-bucket',
            'key': 'claims/guideline.txt'
        }

        with patch.object(lambda_function, 'generate_embedding', return_value=[0.1] * 1536):
            result = lambda_function.lambda_handler(event, lambda_context)

            assert result['statusCode'] == 200
            assert result['doc_type'] == 'claims_guideline'

    def test_determine_doc_type(self):
        """Test document type determination from S3 key"""
        assert lambda_function.determine_doc_type('policies/auto_policy.txt') == 'policy'
        assert lambda_function.determine_doc_type('claims/processing.txt') == 'claims_guideline'
        assert lambda_function.determine_doc_type('compliance/gdpr.txt') == 'compliance'
        assert lambda_function.determine_doc_type('faq/customer_faq.txt') == 'faq'
        assert lambda_function.determine_doc_type('templates/response.txt') == 'template'
        assert lambda_function.determine_doc_type('other/misc.txt') == 'general'

    def test_chunk_document_small_text(self):
        """Test chunking with text smaller than chunk size"""
        text = "This is a short document."

        chunks = lambda_function.chunk_document(text, chunk_size=100, overlap=10)

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_document_large_text(self):
        """Test chunking with text larger than chunk size"""
        # Create text with 200 words
        text = " ".join([f"word{i}" for i in range(200)])

        chunks = lambda_function.chunk_document(text, chunk_size=50, overlap=10)

        assert len(chunks) > 1
        # Check overlap exists
        assert len(chunks) >= 3

    def test_chunk_document_with_overlap(self):
        """Test that chunks have proper overlap"""
        text = " ".join([f"word{i}" for i in range(100)])

        chunks = lambda_function.chunk_document(text, chunk_size=20, overlap=5)

        # Verify overlap by checking last words of chunk N match first words of chunk N+1
        assert len(chunks) > 1

    def test_store_embedding(self, lambda_env_vars, dynamodb_tables):
        """Test embedding storage to DynamoDB"""
        embedding = [0.1, 0.2, 0.3] * 512  # Mock 1536-dim embedding
        content = "Test insurance policy content"

        lambda_function.store_embedding(
            doc_id='test_doc_001',
            content=content,
            embedding=embedding,
            doc_type='policy',
            source_key='policies/test.txt',
            chunk_index=0
        )

        # Verify data was stored
        table = dynamodb_tables['embeddings']
        response = table.get_item(Key={'doc_id': 'test_doc_001'})

        assert 'Item' in response
        item = response['Item']
        assert item['doc_id'] == 'test_doc_001'
        assert item['doc_type'] == 'policy'
        assert item['content'] == content
        # Embedding should be stored as JSON string
        assert isinstance(item['embedding'], str)
        assert len(json.loads(item['embedding'])) == len(embedding)

    def test_store_embedding_truncates_long_content(self, lambda_env_vars, dynamodb_tables):
        """Test that long content is truncated to 1000 chars"""
        embedding = [0.1] * 1536
        long_content = "x" * 2000  # 2000 characters

        lambda_function.store_embedding(
            doc_id='test_long',
            content=long_content,
            embedding=embedding,
            doc_type='policy',
            source_key='test.txt',
            chunk_index=0
        )

        table = dynamodb_tables['embeddings']
        response = table.get_item(Key={'doc_id': 'test_long'})
        item = response['Item']

        # Content should be truncated to 1000 chars
        assert len(item['content']) == 1000

    def test_generate_embedding_truncates_long_text(self, lambda_env_vars):
        """Test that text longer than 8000 chars is truncated before embedding"""
        long_text = "x" * 10000

        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = json.dumps({
            'embedding': [0.1] * 1536
        }).encode('utf-8')

        with patch.object(lambda_function.bedrock_runtime, 'invoke_model', return_value=mock_response) as mock_invoke:
            embedding = lambda_function.generate_embedding(long_text)

            # Verify model was called with truncated text
            call_args = mock_invoke.call_args
            request_body = json.loads(call_args[1]['body'])
            assert len(request_body['inputText']) == 8000

    def test_lambda_handler_error_handling(self, lambda_env_vars, lambda_context):
        """Test error handling for missing bucket/key"""
        event = {}  # Missing required fields

        result = lambda_function.lambda_handler(event, lambda_context)

        assert result['statusCode'] == 500
        assert 'error' in result


class TestEmbeddingGeneration:
    """Test embedding generation via Bedrock"""

    def test_generate_embedding_success(self, lambda_env_vars):
        """Test successful embedding generation"""
        test_text = "This is a test insurance document."

        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = json.dumps({
            'embedding': [0.1] * 1536
        }).encode('utf-8')

        with patch.object(lambda_function.bedrock_runtime, 'invoke_model', return_value=mock_response):
            embedding = lambda_function.generate_embedding(test_text)

            assert len(embedding) == 1536
            assert all(isinstance(x, float) for x in embedding)

    def test_generate_embedding_error(self, lambda_env_vars):
        """Test embedding generation error handling"""
        with patch.object(lambda_function.bedrock_runtime, 'invoke_model', side_effect=Exception('Bedrock error')):
            with pytest.raises(Exception) as exc_info:
                lambda_function.generate_embedding("test")

            assert 'Bedrock error' in str(exc_info.value)
