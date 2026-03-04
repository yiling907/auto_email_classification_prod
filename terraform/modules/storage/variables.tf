variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "email_parser_lambda_arn" {
  description = "ARN of the email parser Lambda function"
  type        = string
  default     = ""
}

variable "email_parser_lambda_permission_id" {
  description = "ID of the Lambda permission for S3 to invoke email parser"
  type        = string
  default     = ""
}

variable "rag_ingestion_lambda_arn" {
  description = "ARN of the RAG ingestion Lambda function"
  type        = string
  default     = ""
}

variable "rag_ingestion_lambda_permission_id" {
  description = "ID of the Lambda permission for S3 to invoke RAG ingestion"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Common tags for resources"
  type        = map(string)
}
