# Lambda module - Deploy all Lambda functions

locals {
  resource_prefix = "${var.project_name}-${var.environment}"
  lambda_source_path = "${path.root}/../lambda"
}

# Data source to package Lambda functions
data "archive_file" "email_parser" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/email_parser"
  output_path = "${path.module}/builds/email_parser.zip"
}

data "archive_file" "rag_ingestion" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/rag_ingestion"
  output_path = "${path.module}/builds/rag_ingestion.zip"
}

data "archive_file" "rag_retrieval" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/rag_retrieval"
  output_path = "${path.module}/builds/rag_retrieval.zip"
}

data "archive_file" "claude_response" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/claude_response"
  output_path = "${path.module}/builds/claude_response.zip"
}

data "archive_file" "multi_llm_inference" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/multi_llm_inference"
  output_path = "${path.module}/builds/multi_llm_inference.zip"
}

data "archive_file" "evaluation_metrics" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/evaluation_metrics"
  output_path = "${path.module}/builds/evaluation_metrics.zip"
}

# Email Parser Lambda
resource "aws_lambda_function" "email_parser" {
  filename         = data.archive_file.email_parser.output_path
  function_name    = "${local.resource_prefix}-email-parser"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 60
  memory_size     = 512
  source_code_hash = data.archive_file.email_parser.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME = var.email_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-email-parser" })
}

resource "aws_cloudwatch_log_group" "email_parser" {
  name              = "/aws/lambda/${aws_lambda_function.email_parser.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# RAG Ingestion Lambda
resource "aws_lambda_function" "rag_ingestion" {
  filename         = data.archive_file.rag_ingestion.output_path
  function_name    = "${local.resource_prefix}-rag-ingestion"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 300  # 5 minutes for processing documents
  memory_size     = 1024
  source_code_hash = data.archive_file.rag_ingestion.output_base64sha256

  environment {
    variables = {
      EMBEDDINGS_TABLE_NAME = var.embeddings_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-rag-ingestion" })
}

resource "aws_cloudwatch_log_group" "rag_ingestion" {
  name              = "/aws/lambda/${aws_lambda_function.rag_ingestion.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# RAG Retrieval Lambda
resource "aws_lambda_function" "rag_retrieval" {
  filename         = data.archive_file.rag_retrieval.output_path
  function_name    = "${local.resource_prefix}-rag-retrieval"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 60
  memory_size     = 512
  source_code_hash = data.archive_file.rag_retrieval.output_base64sha256

  environment {
    variables = {
      EMBEDDINGS_TABLE_NAME = var.embeddings_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-rag-retrieval" })
}

resource "aws_cloudwatch_log_group" "rag_retrieval" {
  name              = "/aws/lambda/${aws_lambda_function.rag_retrieval.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Claude Response Lambda
resource "aws_lambda_function" "claude_response" {
  filename         = data.archive_file.claude_response.output_path
  function_name    = "${local.resource_prefix}-claude-response"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 120  # 2 minutes for Claude API
  memory_size     = 1024
  source_code_hash = data.archive_file.claude_response.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME = var.email_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-claude-response" })
}

resource "aws_cloudwatch_log_group" "claude_response" {
  name              = "/aws/lambda/${aws_lambda_function.claude_response.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Multi-LLM Inference Lambda
resource "aws_lambda_function" "multi_llm_inference" {
  filename         = data.archive_file.multi_llm_inference.output_path
  function_name    = "${local.resource_prefix}-multi-llm-inference"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 180  # 3 minutes for parallel model calls
  memory_size     = 1024
  source_code_hash = data.archive_file.multi_llm_inference.output_base64sha256

  environment {
    variables = {
      MODEL_METRICS_TABLE_NAME = var.model_metrics_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-multi-llm-inference" })
}

resource "aws_cloudwatch_log_group" "multi_llm_inference" {
  name              = "/aws/lambda/${aws_lambda_function.multi_llm_inference.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Evaluation Metrics Lambda
resource "aws_lambda_function" "evaluation_metrics" {
  filename         = data.archive_file.evaluation_metrics.output_path
  function_name    = "${local.resource_prefix}-evaluation-metrics"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 60
  memory_size     = 512
  source_code_hash = data.archive_file.evaluation_metrics.output_base64sha256

  environment {
    variables = {
      MODEL_METRICS_TABLE_NAME = var.model_metrics_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-evaluation-metrics" })
}

resource "aws_cloudwatch_log_group" "evaluation_metrics" {
  name              = "/aws/lambda/${aws_lambda_function.evaluation_metrics.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# S3 trigger for RAG ingestion (when new documents are uploaded)
resource "aws_lambda_permission" "allow_s3_rag_ingestion" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rag_ingestion.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = "arn:aws:s3:::${var.knowledge_base_bucket_name}"
}

# S3 trigger for email parser (when new emails are uploaded)
resource "aws_lambda_permission" "allow_s3_email_parser" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.email_parser.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = "arn:aws:s3:::${var.email_bucket_name}"
}
