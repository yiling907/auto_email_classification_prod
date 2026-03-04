# Bedrock module - Model access configuration

# Note: Bedrock model access must be enabled manually in the AWS Console
# This module is primarily for documentation and future automation

locals {
  resource_prefix = "${var.project_name}-${var.environment}"
}

# Output the models that need to be enabled
output "required_models" {
  description = "List of Bedrock models that need access enabled"
  value       = var.bedrock_models
}

output "setup_instructions" {
  description = "Instructions for enabling Bedrock model access"
  value = <<-EOT
    To use this project, you must enable access to the following Bedrock models:

    1. Go to AWS Bedrock Console
    2. Navigate to "Model access"
    3. Request access for the following models:
       ${join("\n       ", var.bedrock_models)}

    4. Wait for approval (typically instant for Claude and Titan models)

    Note: This is a manual step that cannot be automated via Terraform.
  EOT
}
