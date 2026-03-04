variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "email_bucket_arn" {
  description = "ARN of the email S3 bucket"
  type        = string
}

variable "knowledge_base_bucket_arn" {
  description = "ARN of the knowledge base S3 bucket"
  type        = string
}

variable "logs_bucket_arn" {
  description = "ARN of the logs S3 bucket"
  type        = string
}

variable "email_table_arn" {
  description = "ARN of the email processing DynamoDB table"
  type        = string
}

variable "model_metrics_table_arn" {
  description = "ARN of the model metrics DynamoDB table"
  type        = string
}

variable "embeddings_table_arn" {
  description = "ARN of the embeddings DynamoDB table"
  type        = string
}

variable "tags" {
  description = "Common tags for resources"
  type        = map(string)
}
