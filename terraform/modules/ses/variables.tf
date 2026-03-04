# SES Module Variables (IMAP version - sending only)

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

# REMOVED (no longer needed with IMAP receiving):
# - ses_receipt_recipients (no SES receipt rules)
# - email_bucket_name (not used by SES module)
# - email_bucket_arn (not used by SES module)
# - email_receiver_lambda_arn (Lambda removed)
# - email_receiver_lambda_name (Lambda removed)
