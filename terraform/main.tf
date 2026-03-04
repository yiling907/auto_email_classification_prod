# Main Terraform configuration for InsureMail AI

locals {
  resource_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(
    var.tags,
    {
      Environment = var.environment
    }
  )
}

# Storage module - S3 buckets and DynamoDB tables
# Note: Must be created before Lambda to avoid circular dependency
module "storage" {
  source = "./modules/storage"

  project_name = var.project_name
  environment  = var.environment
  tags         = local.common_tags

  # S3 event triggers (configured after Lambda module)
  email_parser_lambda_arn            = module.lambda.email_parser_arn
  email_parser_lambda_permission_id  = module.lambda.email_parser_lambda_permission_id
  rag_ingestion_lambda_arn           = module.lambda.rag_ingestion_arn
  rag_ingestion_lambda_permission_id = module.lambda.rag_ingestion_lambda_permission_id
}

# IAM module - Roles and policies for Lambda and Step Functions
module "iam" {
  source = "./modules/iam"

  project_name          = var.project_name
  environment           = var.environment
  aws_region            = var.aws_region
  email_bucket_arn      = module.storage.email_bucket_arn
  knowledge_base_bucket_arn = module.storage.knowledge_base_bucket_arn
  logs_bucket_arn       = module.storage.logs_bucket_arn
  email_table_arn       = module.storage.email_table_arn
  model_metrics_table_arn = module.storage.model_metrics_table_arn
  embeddings_table_arn  = module.storage.embeddings_table_arn
  tags                  = local.common_tags
}

# Lambda module - All Lambda functions
module "lambda" {
  source = "./modules/lambda"

  project_name              = var.project_name
  environment               = var.environment
  lambda_runtime            = var.lambda_runtime
  lambda_execution_role_arn = module.iam.lambda_execution_role_arn
  email_bucket_name         = module.storage.email_bucket_name
  knowledge_base_bucket_name = module.storage.knowledge_base_bucket_name
  email_table_name          = module.storage.email_table_name
  model_metrics_table_name  = module.storage.model_metrics_table_name
  embeddings_table_name     = module.storage.embeddings_table_name
  log_retention_days        = var.log_retention_days
  state_machine_arn         = module.step_functions.state_machine_arn
  sender_email              = var.sender_email
  sender_name               = var.sender_name

  # Gmail IMAP Configuration
  gmail_address         = var.gmail_address
  gmail_app_password    = var.gmail_app_password
  imap_server           = var.imap_server
  mark_emails_as_read   = var.mark_emails_as_read ? "true" : "false"

  tags                      = local.common_tags
}

# Step Functions module - Orchestration workflow
module "step_functions" {
  source = "./modules/step-functions"

  project_name                    = var.project_name
  environment                     = var.environment
  step_functions_role_arn         = module.iam.step_functions_role_arn
  email_parser_lambda_arn         = module.lambda.email_parser_arn
  rag_retrieval_lambda_arn        = module.lambda.rag_retrieval_arn
  claude_response_lambda_arn      = module.lambda.claude_response_arn
  multi_llm_inference_lambda_arn  = module.lambda.multi_llm_inference_arn
  email_sender_lambda_arn         = module.lambda.email_sender_arn
  tags                            = local.common_tags
}

# Bedrock module - Model access configuration
module "bedrock" {
  source = "./modules/bedrock"

  project_name   = var.project_name
  environment    = var.environment
  bedrock_models = var.bedrock_models
  tags           = local.common_tags
}

# Monitoring module - CloudWatch metrics and alarms
module "monitoring" {
  source = "./modules/monitoring"

  project_name                     = var.project_name
  environment                      = var.environment
  log_retention_days               = var.log_retention_days
  state_machine_arn                = module.step_functions.state_machine_arn
  email_parser_function_name       = module.lambda.email_parser_name
  evaluation_metrics_lambda_arn    = module.lambda.evaluation_metrics_arn
  gmail_imap_poller_lambda_arn     = module.lambda.gmail_imap_poller_arn
  gmail_imap_poller_lambda_name    = module.lambda.gmail_imap_poller_name
  tags                             = local.common_tags
}

# API Gateway module - REST API for dashboard
module "api_gateway" {
  source = "./modules/api-gateway"

  project_name            = var.project_name
  environment             = var.environment
  api_handler_lambda_arn  = module.lambda.api_handlers_arn
  api_handler_lambda_name = module.lambda.api_handlers_name
  tags                    = local.common_tags
}

# SES module - Email sending only (receiving via Gmail IMAP)
module "ses" {
  source = "./modules/ses"

  project_name       = var.project_name
  environment        = var.environment
  support_email      = var.sender_email
  log_retention_days = var.log_retention_days
  tags               = local.common_tags
}
