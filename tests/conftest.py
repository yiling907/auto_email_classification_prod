"""
Pytest configuration and shared fixtures for Lambda function tests
"""
import os
import json
import pytest
from decimal import Decimal
from datetime import datetime
from moto import mock_aws
import boto3

# Set environment variables before any lambda module is imported
_DEFAULT_ENV = {
    'AWS_ACCESS_KEY_ID':              'testing',
    'AWS_SECRET_ACCESS_KEY':          'testing',
    'AWS_SECURITY_TOKEN':             'testing',
    'AWS_SESSION_TOKEN':              'testing',
    'AWS_DEFAULT_REGION':             'us-east-1',
    'EMAIL_TABLE_NAME':               'test-emails',
    'MODEL_METRICS_TABLE_NAME':       'test-model-metrics',
    'EMBEDDINGS_TABLE_NAME':          'test-embeddings',
    'STATE_MACHINE_ARN':              'arn:aws:states:us-east-1:123456789012:stateMachine:test-state-machine',
    'EMAIL_BUCKET_NAME':              'test-emails-bucket',
    'KNOWLEDGE_BASE_BUCKET_NAME':     'test-knowledge-base-bucket',
    'KNOWLEDGE_BASE_BUCKET':          'test-knowledge-base-bucket',
    'LOGS_BUCKET':                    'test-logs-bucket',
    'SENDER_EMAIL':                   'test@example.com',
    'SENDER_NAME':                    'Test Sender',
    'PRIMARY_MODEL_ID':               'mistral.mistral-7b-instruct-v0:2',
    'EVALUATION_METRICS_FUNCTION_NAME': 'test-evaluation-metrics',
    'BEDROCK_EVAL_ROLE_ARN':          'arn:aws:iam::123456789012:role/test-bedrock-eval-role',
}
for _k, _v in _DEFAULT_ENV.items():
    os.environ.setdefault(_k, _v)


# Set environment variables for testing
@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Mock AWS credentials for moto"""
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'testing')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'testing')
    monkeypatch.setenv('AWS_SECURITY_TOKEN', 'testing')
    monkeypatch.setenv('AWS_SESSION_TOKEN', 'testing')
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')


@pytest.fixture
def lambda_env_vars(monkeypatch):
    """Set common Lambda environment variables"""
    monkeypatch.setenv('EMAIL_TABLE_NAME', 'test-emails')
    monkeypatch.setenv('MODEL_METRICS_TABLE_NAME', 'test-model-metrics')
    monkeypatch.setenv('EMBEDDINGS_TABLE_NAME', 'test-embeddings')
    monkeypatch.setenv('STATE_MACHINE_ARN', 'arn:aws:states:us-east-1:123456789012:stateMachine:test-state-machine')
    monkeypatch.setenv('EMAIL_BUCKET_NAME', 'test-emails-bucket')
    monkeypatch.setenv('KNOWLEDGE_BASE_BUCKET_NAME', 'test-knowledge-base-bucket')
    monkeypatch.setenv('SENDER_EMAIL', 'test@example.com')
    monkeypatch.setenv('SENDER_NAME', 'Test Sender')
    monkeypatch.setenv('PRIMARY_MODEL_ID', 'mistral.mistral-7b-instruct-v0:2')
    monkeypatch.setenv('EVALUATION_METRICS_FUNCTION_NAME', 'test-evaluation-metrics')


@pytest.fixture
def dynamodb_tables():
    """Create mock DynamoDB tables"""
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Email processing table
        email_table = dynamodb.create_table(
            TableName='test-emails',
            KeySchema=[{'AttributeName': 'email_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'email_id', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )

        # Model metrics table — PK: metric_key = "{model_id}#{task_type}#{email_id}"
        metrics_table = dynamodb.create_table(
            TableName='test-model-metrics',
            KeySchema=[{'AttributeName': 'metric_key', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'metric_key', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )

        # Embeddings table
        embeddings_table = dynamodb.create_table(
            TableName='test-embeddings',
            KeySchema=[{'AttributeName': 'doc_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'doc_id', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )

        yield {
            'email': email_table,
            'metrics': metrics_table,
            'embeddings': embeddings_table
        }


@pytest.fixture
def s3_buckets():
    """Create mock S3 buckets"""
    with mock_aws():
        s3 = boto3.client('s3', region_name='us-east-1')

        s3.create_bucket(Bucket='test-emails-bucket')
        s3.create_bucket(Bucket='test-knowledge-base-bucket')

        yield s3


@pytest.fixture
def sample_email():
    """Sample email data for testing — field names match emails.jsonl schema."""
    return {
        'sender_email': 'customer@example.com',
        'sender_name': 'Test Customer',
        'mailbox': 'support@demohealth.ie',
        'subject': 'Question about my claim status',
        'body_text': 'I submitted a claim last week for POL-IE-123456. What is the status?',
        'body_html': '',
        'received_at': '2026-03-04T10:30:00Z',
        # Keep legacy aliases so integration test raw-email construction works
        'from_address': 'customer@example.com',
        'to_address': 'support@demohealth.ie',
        'body': 'I submitted a claim last week for POL-IE-123456. What is the status?',
        'timestamp': '2026-03-04T10:30:00Z',
    }


@pytest.fixture
def sample_rag_document():
    """Sample RAG document for testing"""
    return {
        'doc_id': 'policy_001',
        'doc_type': 'policy',
        'content': 'Insurance policy terms and conditions for claim processing.',
        'embedding': [0.1] * 1536,  # Mock embedding vector
        'metadata': {
            'source_key': 'policies/policy_001.txt',
            'chunk_index': 0
        }
    }


@pytest.fixture
def sample_model_metrics():
    """Sample model metrics for testing"""
    return {
        'task_type': 'intent_classification',
        'model_timestamp': 'mistral-7b#2026-03-04T10:30:00.000Z',
        'model_name': 'mistral-7b',
        'model_id': 'mistral.mistral-7b-instruct-v0:2',
        'input_tokens': 450,
        'output_tokens': 85,
        'latency_ms': Decimal('1850.5'),
        'cost_usd': Decimal('0.000085'),
        'success': True,
        'timestamp': '2026-03-04T10:30:00.000Z'
    }


@pytest.fixture
def mock_bedrock_response():
    """Mock Bedrock API response"""
    return {
        'mistral': {
            'outputs': [{
                'text': 'claim_inquiry'
            }]
        },
        'llama': {
            'generation': 'claim_inquiry',
            'prompt_token_count': 450,
            'generation_token_count': 10
        },
        'claude': {
            'content': [{
                'text': 'claim_inquiry'
            }],
            'usage': {
                'input_tokens': 450,
                'output_tokens': 10
            }
        }
    }


@pytest.fixture
def lambda_context():
    """Mock Lambda context object"""
    class LambdaContext:
        def __init__(self):
            self.function_name = 'test-function'
            self.function_version = '$LATEST'
            self.invoked_function_arn = 'arn:aws:lambda:us-east-1:123456789012:function:test-function'
            self.memory_limit_in_mb = 512
            self.aws_request_id = 'test-request-id'
            self.log_group_name = '/aws/lambda/test-function'
            self.log_stream_name = 'test-stream'

        def get_remaining_time_in_millis(self):
            return 300000

    return LambdaContext()
