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

data "archive_file" "llm_response" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/llm_response"
  output_path = "${path.module}/builds/llm_response.zip"
}

data "archive_file" "classify_intent_by_llm" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/classify_intent_by_llm"
  output_path = "${path.module}/builds/classify_intent_by_llm.zip"
}

data "archive_file" "classify_intent_by_biobert" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/classify_intent_by_biobert"
  output_path = "${path.module}/builds/classify_intent_by_biobert.zip"
}

# Email Parser Lambda
resource "aws_lambda_function" "email_parser" {
  filename         = data.archive_file.email_parser.output_path
  function_name    = "${local.resource_prefix}-email-parser"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 180  # 3 minutes: parsing + Textract OCR + Bedrock extraction
  memory_size     = 512
  source_code_hash = data.archive_file.email_parser.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME = var.email_table_name
      ENTITY_MODEL_ID  = "anthropic.claude-3-haiku-20240307-v1:0"
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
resource "aws_lambda_function" "llm_response" {
  filename         = data.archive_file.llm_response.output_path
  function_name    = "${local.resource_prefix}-llm-response"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 180  # 3 minutes: primary model call + evaluator model call
  memory_size     = 1024
  source_code_hash = data.archive_file.llm_response.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME         = var.email_table_name
      MODEL_METRICS_TABLE_NAME = var.model_metrics_table_name
      ACTIVE_MODEL             = "mistral-7b"
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-llm-response" })
}

resource "aws_cloudwatch_log_group" "llm_response" {
  name              = "/aws/lambda/${aws_lambda_function.llm_response.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# LLM Intent Classification Lambda
resource "aws_lambda_function" "classify_intent_by_llm" {
  filename         = data.archive_file.classify_intent_by_llm.output_path
  function_name    = "${local.resource_prefix}-classify-intent-by-llm"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 180  # 3 minutes for parallel model calls
  memory_size     = 1024
  source_code_hash = data.archive_file.classify_intent_by_llm.output_base64sha256

  environment {
    variables = {
      MODEL_METRICS_TABLE_NAME = var.model_metrics_table_name
      EMAIL_TABLE_NAME         = var.email_table_name
      ACTIVE_MODEL             = "mistral-7b"
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-classify-intent-by-llm" })
}

resource "aws_cloudwatch_log_group" "classify_intent_by_llm" {
  name              = "/aws/lambda/${aws_lambda_function.classify_intent_by_llm.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# BioBERT Intent Classification Lambda
resource "aws_lambda_function" "classify_intent_by_biobert" {
  filename         = data.archive_file.classify_intent_by_biobert.output_path
  function_name    = "${local.resource_prefix}-classify-intent-by-biobert"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 60
  memory_size     = 512
  source_code_hash = data.archive_file.classify_intent_by_biobert.output_base64sha256

  environment {
    variables = {
      SAGEMAKER_ENDPOINT_NAME = var.sagemaker_endpoint_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-classify-intent-by-biobert" })
}

resource "aws_cloudwatch_log_group" "classify_intent_by_biobert" {
  name              = "/aws/lambda/${aws_lambda_function.classify_intent_by_biobert.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Data source to package API handler Lambda
data "archive_file" "api_handlers" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/api_handlers"
  output_path = "${path.module}/builds/api_handlers.zip"
}

# API Handlers Lambda (for dashboard API)
resource "aws_lambda_function" "api_handlers" {
  filename         = data.archive_file.api_handlers.output_path
  function_name    = "${local.resource_prefix}-api-handlers"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 30
  memory_size     = 512
  source_code_hash = data.archive_file.api_handlers.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME                  = var.email_table_name
      MODEL_METRICS_TABLE_NAME          = var.model_metrics_table_name
      EMBEDDINGS_TABLE_NAME             = var.embeddings_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-api-handlers" })
}

resource "aws_cloudwatch_log_group" "api_handlers" {
  name              = "/aws/lambda/${aws_lambda_function.api_handlers.function_name}"
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

# Gmail IMAP Poller Lambda (replaces SES email receiver)
data "archive_file" "gmail_imap_poller" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/gmail_imap_poller"
  output_path = "${path.module}/builds/gmail_imap_poller.zip"
}

resource "aws_lambda_function" "gmail_imap_poller" {
  filename         = data.archive_file.gmail_imap_poller.output_path
  function_name    = "${local.resource_prefix}-gmail-imap-poller"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 120  # 2 minutes for IMAP connection and processing
  memory_size     = 256
  source_code_hash = data.archive_file.gmail_imap_poller.output_base64sha256

  environment {
    variables = {
      GMAIL_ADDRESS       = var.gmail_address
      GMAIL_APP_PASSWORD  = var.gmail_app_password
      S3_BUCKET          = var.email_bucket_name
      STATE_MACHINE_ARN  = var.state_machine_arn
      IMAP_SERVER        = var.imap_server
      MARK_AS_READ       = var.mark_emails_as_read
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-gmail-imap-poller" })
}

resource "aws_cloudwatch_log_group" "gmail_imap_poller" {
  name              = "/aws/lambda/${aws_lambda_function.gmail_imap_poller.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}


# CRM Validation Lambda
data "archive_file" "crm_validation" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/crm_validation"
  output_path = "${path.module}/builds/crm_validation.zip"
}

resource "aws_lambda_function" "crm_validation" {
  filename         = data.archive_file.crm_validation.output_path
  function_name    = "${local.resource_prefix}-crm-validation"
  role             = var.lambda_execution_role_arn
  handler          = "lambda_function.lambda_handler"
  runtime          = var.lambda_runtime
  timeout          = 60
  memory_size      = 512
  source_code_hash = data.archive_file.crm_validation.output_base64sha256

  environment {
    variables = {
      CUSTOMERS_TABLE_NAME = var.customers_table_name
      TEXT2SQL_MODEL_ID    = "mistral.mistral-7b-instruct-v0:2"
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-crm-validation" })
}

resource "aws_cloudwatch_log_group" "crm_validation" {
  name              = "/aws/lambda/${aws_lambda_function.crm_validation.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Data source to package Email Sender Lambda
data "archive_file" "email_sender" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/email_sender"
  output_path = "${path.module}/builds/email_sender.zip"
}

# Email Sender Lambda (sends responses via SES)
resource "aws_lambda_function" "email_sender" {
  filename         = data.archive_file.email_sender.output_path
  function_name    = "${local.resource_prefix}-email-sender"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 30
  memory_size     = 256
  source_code_hash = data.archive_file.email_sender.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME = var.email_table_name
      SENDER_EMAIL     = var.sender_email
      SENDER_NAME      = var.sender_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-email-sender" })
}

resource "aws_cloudwatch_log_group" "email_sender" {
  name              = "/aws/lambda/${aws_lambda_function.email_sender.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Save Result Lambda
data "archive_file" "save_result" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/save_result"
  output_path = "${path.module}/builds/save_result.zip"
}

resource "aws_lambda_function" "save_result" {
  filename         = data.archive_file.save_result.output_path
  function_name    = "${local.resource_prefix}-save-result"
  role             = var.lambda_execution_role_arn
  handler          = "lambda_function.lambda_handler"
  runtime          = var.lambda_runtime
  timeout          = 30
  memory_size      = 128
  source_code_hash = data.archive_file.save_result.output_base64sha256

  environment {
    variables = {
      PIPELINE_RESULTS_TABLE_NAME = var.pipeline_results_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-save-result" })
}

resource "aws_cloudwatch_log_group" "save_result" {
  name              = "/aws/lambda/${aws_lambda_function.save_result.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# SageMaker Inference Lambda — proxies POST /api/model/inference to the SageMaker GPU endpoint
data "archive_file" "sagemaker_inference" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/sagemaker_inference"
  output_path = "${path.module}/builds/sagemaker_inference.zip"
}

resource "aws_lambda_function" "sagemaker_inference" {
  filename         = data.archive_file.sagemaker_inference.output_path
  function_name    = "${local.resource_prefix}-sagemaker-inference"
  role             = var.lambda_execution_role_arn
  handler          = "lambda_function.lambda_handler"
  runtime          = var.lambda_runtime
  timeout          = 60    # SageMaker inference can take several seconds on first call
  memory_size      = 256
  source_code_hash = data.archive_file.sagemaker_inference.output_base64sha256

  environment {
    variables = {
      SAGEMAKER_ENDPOINT_NAME = var.sagemaker_endpoint_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-sagemaker-inference" })
}

resource "aws_cloudwatch_log_group" "sagemaker_inference" {
  name              = "/aws/lambda/${aws_lambda_function.sagemaker_inference.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}
