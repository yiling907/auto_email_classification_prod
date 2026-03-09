variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "step_functions_role_arn" {
  description = "ARN of the Step Functions execution role"
  type        = string
}

variable "email_parser_lambda_arn" {
  description = "ARN of the email parser Lambda function"
  type        = string
}

variable "rag_retrieval_lambda_arn" {
  description = "ARN of the RAG retrieval Lambda function"
  type        = string
}

variable "claude_response_lambda_arn" {
  description = "ARN of the Claude response Lambda function"
  type        = string
}

variable "classify_intent_lambda_arn" {
  description = "ARN of the multi-LLM inference Lambda function"
  type        = string
}

variable "email_sender_lambda_arn" {
  description = "ARN of the email sender Lambda function"
  type        = string
}

variable "tags" {
  description = "Common tags for resources"
  type        = map(string)
}
