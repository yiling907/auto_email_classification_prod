variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "lambda_runtime" {
  description = "Lambda runtime version"
  type        = string
}

variable "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role"
  type        = string
}

variable "email_bucket_name" {
  description = "Name of the email S3 bucket"
  type        = string
}

variable "knowledge_base_bucket_name" {
  description = "Name of the knowledge base S3 bucket"
  type        = string
}

variable "email_table_name" {
  description = "Name of the email processing DynamoDB table"
  type        = string
}

variable "model_metrics_table_name" {
  description = "Name of the model metrics DynamoDB table"
  type        = string
}

variable "embeddings_table_name" {
  description = "Name of the embeddings DynamoDB table"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
}

variable "tags" {
  description = "Common tags for resources"
  type        = map(string)
}
