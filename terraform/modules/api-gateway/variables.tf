variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "api_handler_lambda_arn" {
  description = "ARN of the API handler Lambda function"
  type        = string
}

variable "api_handler_lambda_name" {
  description = "Name of the API handler Lambda function"
  type        = string
}

variable "tags" {
  description = "Common tags for resources"
  type        = map(string)
}
