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

variable "state_machine_arn" {
  description = "ARN of the Step Functions state machine (for email receiver)"
  type        = string
  default     = ""
}

variable "sender_email" {
  description = "Email address to send responses from (must be verified in SES)"
  type        = string
  default     = "support@example.com"
}

variable "sender_name" {
  description = "Name to display as sender"
  type        = string
  default     = "InsureMail AI Support"
}

variable "tags" {
  description = "Common tags for resources"
  type        = map(string)
}

# Gmail IMAP Configuration
variable "gmail_address" {
  description = "Gmail address for IMAP polling"
  type        = string
  sensitive   = true
}

variable "gmail_app_password" {
  description = "Gmail App Password for IMAP access"
  type        = string
  sensitive   = true
}

variable "imap_server" {
  description = "IMAP server address"
  type        = string
  default     = "imap.gmail.com"
}

variable "mark_emails_as_read" {
  description = "Whether to mark emails as read after processing"
  type        = string
  default     = "true"
}
