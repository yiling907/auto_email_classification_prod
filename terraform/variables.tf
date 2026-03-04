variable "project_name" {
  description = "Project name for resource naming and tagging"
  type        = string
  default     = "insuremail-ai"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region for resource deployment"
  type        = string
  default     = "us-east-1"
}

variable "bedrock_models" {
  description = "List of Bedrock model IDs to enable"
  type        = list(string)
  default = [
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "amazon.titan-embed-text-v1"
    # Note: Removed deprecated models (titan-text-lite-v1, llama3, mistral)
    # Add newer models as needed
  ]
}

variable "lambda_runtime" {
  description = "Lambda runtime version"
  type        = string
  default     = "python3.11"
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 7
}

variable "enable_bedrock_logging" {
  description = "Enable Bedrock API logging"
  type        = bool
  default     = true
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

variable "ses_receipt_recipients" {
  description = "List of email addresses to receive emails. Use empty list for all emails."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default = {
    Project    = "InsureMailAI"
    ManagedBy  = "Terraform"
    Repository = "auto_email_classification_prod"
  }
}
