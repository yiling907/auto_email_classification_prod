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
  description = "List of Bedrock model IDs - Using available open-source models"
  type        = list(string)
  default = [
    # Open Source Models (Verified Working)

    # Mistral 7B Instruct - Open source, most cost-effective
    # ~$0.15 per 1M input tokens, $0.20 per 1M output tokens
    # STATUS: ✅ WORKING
    "mistral.mistral-7b-instruct-v0:2",

    # Meta Llama 3.1 8B Instruct - Open source (via cross-region inference profile)
    # ~$0.30 per 1M input tokens, $0.60 per 1M output tokens
    # STATUS: ✅ WORKING (using inference profile)
    "us.meta.llama3-1-8b-instruct-v1:0",

    # Amazon Titan Embeddings - For RAG
    # ~$0.10 per 1M tokens
    # STATUS: ✅ WORKING
    "amazon.titan-embed-text-v1"

    # REMOVED DEPRECATED MODELS:
    # - amazon.titan-text-express-v1 (EOL - reached end of life)
    # - Direct model IDs require provisioned throughput (use inference profiles instead)
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
  default     = "shiyizhiya@gmail.com"
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

# Gmail IMAP Configuration
variable "gmail_address" {
  description = "Gmail address for IMAP polling (e.g., your-email@gmail.com)"
  type        = string
  sensitive   = true
}

variable "gmail_app_password" {
  description = "Gmail App Password for IMAP access (NOT your regular password - generate at https://myaccount.google.com/apppasswords)"
  type        = string
  sensitive   = true
}

variable "imap_server" {
  description = "IMAP server address (default: imap.gmail.com)"
  type        = string
  default     = "imap.gmail.com"
}

variable "imap_poll_interval_minutes" {
  description = "How often to poll Gmail inbox (in minutes)"
  type        = number
  default     = 5
}

variable "mark_emails_as_read" {
  description = "Whether to mark processed emails as read in Gmail"
  type        = bool
  default     = true
}
