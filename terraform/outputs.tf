# Terraform outputs

# Storage outputs
output "email_bucket_name" {
  description = "Name of the S3 bucket for raw emails"
  value       = module.storage.email_bucket_name
}

output "knowledge_base_bucket_name" {
  description = "Name of the S3 bucket for knowledge base documents"
  value       = module.storage.knowledge_base_bucket_name
}

output "logs_bucket_name" {
  description = "Name of the S3 bucket for logs and evaluation results"
  value       = module.storage.logs_bucket_name
}

output "email_table_name" {
  description = "Name of the DynamoDB table for email processing data"
  value       = module.storage.email_table_name
}

output "model_metrics_table_name" {
  description = "Name of the DynamoDB table for model performance metrics"
  value       = module.storage.model_metrics_table_name
}

output "embeddings_table_name" {
  description = "Name of the DynamoDB table for knowledge base embeddings"
  value       = module.storage.embeddings_table_name
}

# Lambda outputs
output "lambda_functions" {
  description = "Map of Lambda function names to ARNs"
  value = {
    email_parser        = module.lambda.email_parser_arn
    rag_ingestion       = module.lambda.rag_ingestion_arn
    rag_retrieval       = module.lambda.rag_retrieval_arn
    claude_response     = module.lambda.claude_response_arn
    classify_intent = module.lambda.classify_intent_arn
    evaluation_metrics  = module.lambda.evaluation_metrics_arn
  }
}

# Step Functions output
output "state_machine_arn" {
  description = "ARN of the Step Functions state machine"
  value       = module.step_functions.state_machine_arn
}

output "state_machine_name" {
  description = "Name of the Step Functions state machine"
  value       = module.step_functions.state_machine_name
}

# IAM outputs
output "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = module.iam.lambda_execution_role_arn
}

output "step_functions_role_arn" {
  description = "ARN of the Step Functions execution role"
  value       = module.iam.step_functions_role_arn
}

# API Gateway output
output "api_gateway_url" {
  description = "Base URL of the API Gateway for dashboard"
  value       = module.api_gateway.api_gateway_url
}
