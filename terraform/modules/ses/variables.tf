# SES Module Variables

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment (dev/staging/prod)"
  type        = string
}

variable "support_email" {
  description = "Email address for SES identity (for sending). Leave empty to skip email identity creation."
  type        = string
  default     = ""
}

variable "ses_receipt_recipients" {
  description = "List of email addresses to receive emails. Use empty list for all emails to this domain."
  type        = list(string)
  default     = []
}

variable "email_bucket_name" {
  description = "S3 bucket name for storing emails"
  type        = string
}

variable "email_bucket_arn" {
  description = "S3 bucket ARN for storing emails"
  type        = string
}

variable "email_receiver_lambda_arn" {
  description = "ARN of the email receiver Lambda function"
  type        = string
}

variable "email_receiver_lambda_name" {
  description = "Name of the email receiver Lambda function"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention period in days"
  type        = number
  default     = 7
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
