variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
}

variable "state_machine_arn" {
  description = "ARN of the Step Functions state machine"
  type        = string
}

variable "email_parser_function_name" {
  description = "Name of the email parser Lambda function"
  type        = string
}

variable "evaluation_metrics_lambda_arn" {
  description = "ARN of the evaluation metrics Lambda function"
  type        = string
}

variable "tags" {
  description = "Common tags for resources"
  type        = map(string)
}
