# Storage module - S3 buckets and DynamoDB tables

locals {
  resource_prefix = "${var.project_name}-${var.environment}"
}

# S3 Bucket for raw emails
resource "aws_s3_bucket" "emails" {
  bucket = "${local.resource_prefix}-emails"
  tags   = merge(var.tags, { Name = "${local.resource_prefix}-emails" })
}

resource "aws_s3_bucket_versioning" "emails" {
  bucket = aws_s3_bucket.emails.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "emails" {
  bucket = aws_s3_bucket.emails.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "emails" {
  bucket = aws_s3_bucket.emails.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# S3 event notification for email parsing (for manually uploaded emails)
# Note: SES-received emails use SNS → Lambda flow, not S3 → Lambda
resource "aws_s3_bucket_notification" "emails" {
  bucket = aws_s3_bucket.emails.id

  lambda_function {
    lambda_function_arn = var.email_parser_lambda_arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [var.email_parser_lambda_permission_id]
}

# S3 Bucket for knowledge base documents
resource "aws_s3_bucket" "knowledge_base" {
  bucket = "${local.resource_prefix}-knowledge-base"
  tags   = merge(var.tags, { Name = "${local.resource_prefix}-knowledge-base" })
}

resource "aws_s3_bucket_versioning" "knowledge_base" {
  bucket = aws_s3_bucket.knowledge_base.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "knowledge_base" {
  bucket = aws_s3_bucket.knowledge_base.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "knowledge_base" {
  bucket = aws_s3_bucket.knowledge_base.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# S3 event notification for RAG ingestion
resource "aws_s3_bucket_notification" "knowledge_base" {
  bucket = aws_s3_bucket.knowledge_base.id

  lambda_function {
    lambda_function_arn = var.rag_ingestion_lambda_arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [var.rag_ingestion_lambda_permission_id]
}

# S3 Bucket for logs and evaluation results
resource "aws_s3_bucket" "logs" {
  bucket = "${local.resource_prefix}-logs"
  tags   = merge(var.tags, { Name = "${local.resource_prefix}-logs" })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "delete-old-logs"
    status = "Enabled"

    expiration {
      days = 30
    }
  }
}

# DynamoDB table for email processing data
resource "aws_dynamodb_table" "email_processing" {
  name         = "${local.resource_prefix}-email-processing"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "email_id"

  attribute {
    name = "email_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  attribute {
    name = "confidence_level"
    type = "S"
  }

  # GSI for querying by timestamp
  global_secondary_index {
    name            = "timestamp-index"
    hash_key        = "confidence_level"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-email-processing" })
}

# DynamoDB table for model performance metrics
# PK: metric_key = "{model_id}#{task_type}#{email_id}"
resource "aws_dynamodb_table" "model_metrics" {
  name         = "${local.resource_prefix}-model-metrics"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "metric_key"

  attribute {
    name = "metric_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-model-metrics" })
}

# DynamoDB table for knowledge base embeddings
resource "aws_dynamodb_table" "embeddings" {
  name         = "${local.resource_prefix}-embeddings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "doc_id"

  attribute {
    name = "doc_id"
    type = "S"
  }

  attribute {
    name = "doc_type"
    type = "S"
  }

  # GSI for querying by document type
  global_secondary_index {
    name            = "doc-type-index"
    hash_key        = "doc_type"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-embeddings" })
}
