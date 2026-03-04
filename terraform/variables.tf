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
  description = "List of Bedrock model IDs - Using open-source models for cost optimization"
  type        = list(string)
  default = [
    # Open Source Models (Free/Low Cost)

    # Meta Llama 3.1 8B Instruct - Open source, cost-effective
    # ~$0.30 per 1M input tokens, $0.60 per 1M output tokens
    "meta.llama3-1-8b-instruct-v1:0",

    # Mistral 7B Instruct - Open source, very cost-effective
    # ~$0.15 per 1M input tokens, $0.20 per 1M output tokens
    "mistral.mistral-7b-instruct-v0:2",

    # Amazon Titan Text Express - AWS native, cost-effective
    # ~$0.20 per 1M input tokens, $0.60 per 1M output tokens
    "amazon.titan-text-express-v1",

    # Amazon Titan Embeddings - For RAG (cheapest embedding model)
    # ~$0.10 per 1M tokens
    "amazon.titan-embed-text-v1"

    # Note: Removed proprietary models:
    # - Claude 3 Haiku ($0.25/$1.25 per 1M) - proprietary
    # - Claude 3 Sonnet ($3/$15 per 1M) - expensive & proprietary
    # Using only open-source alternatives for multi-LLM comparison
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
