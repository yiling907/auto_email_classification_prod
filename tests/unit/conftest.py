"""
Unit-test directory conftest.

Provides shared fixtures used across lambda unit test files.

Each lambda test file imports its own 'lambda_function' module under that
shared name. Python's module cache collides when multiple files are collected
in one pytest session. Each test file handles this by clearing the cache
before its own import (via sys.modules.pop). No additional hooks needed here.
"""

import os
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

KNOWLEDGE_BASE_BUCKET = "test-knowledge-base-bucket"


# ── Environment variable fixture ─────────────────────────────────────────────

@pytest.fixture
def lambda_env_vars(monkeypatch):
    """
    Set the environment variables required by Lambda functions at import time.
    Uses monkeypatch so variables are restored after each test.
    """
    monkeypatch.setenv("EMAIL_TABLE_NAME",       "test-emails")
    monkeypatch.setenv("MODEL_METRICS_TABLE_NAME", "test-model-metrics")
    monkeypatch.setenv("EMBEDDINGS_TABLE_NAME",   "test-embeddings")
    monkeypatch.setenv("CUSTOMERS_TABLE_NAME",    "test-customers")
    monkeypatch.setenv("AWS_DEFAULT_REGION",      "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID",       "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY",   "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN",      "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN",       "testing")


# ── Lambda context fixture ────────────────────────────────────────────────────

@pytest.fixture
def lambda_context():
    """Minimal mock AWS Lambda context object."""
    ctx = MagicMock()
    ctx.function_name = "test-function"
    ctx.aws_request_id = "test-request-id"
    ctx.get_remaining_time_in_millis.return_value = 30000
    return ctx


# ── DynamoDB tables fixture ───────────────────────────────────────────────────

@pytest.fixture
def dynamodb_tables(lambda_env_vars):
    """
    Create moto-backed DynamoDB tables for use in unit tests.
    Returns a dict mapping table roles to boto3 Table objects.
    """
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        emails_table = dynamodb.create_table(
            TableName="test-emails",
            KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        metrics_table = dynamodb.create_table(
            TableName="test-model-metrics",
            KeySchema=[{"AttributeName": "metric_key", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "metric_key", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        embeddings_table = dynamodb.create_table(
            TableName="test-embeddings",
            KeySchema=[{"AttributeName": "doc_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "doc_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        customers_table = dynamodb.create_table(
            TableName="test-customers",
            KeySchema=[{"AttributeName": "customer_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "customer_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        yield {
            "emails":     emails_table,
            "metrics":    metrics_table,
            "embeddings": embeddings_table,
            "customers":  customers_table,
        }


# ── S3 buckets fixture ────────────────────────────────────────────────────────

@pytest.fixture
def s3_buckets(lambda_env_vars):
    """
    Create moto-backed S3 buckets for use in unit tests.
    Returns the boto3 S3 client (buckets are also accessible via boto3.resource).
    """
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=KNOWLEDGE_BASE_BUCKET)
        yield s3


# ── Sample RAG document fixture ───────────────────────────────────────────────

@pytest.fixture
def sample_rag_document():
    """A minimal knowledge-base document suitable for RAG retrieval tests."""
    return {
        "doc_id":    "test-doc-001",
        "doc_type":  "policy",
        "content":   "Out-patient claims must be submitted within 90 days of treatment.",
        "embedding": [0.1] * 1536,
        "metadata":  {"source": "laya_policy.txt", "chunk_index": 0},
    }
