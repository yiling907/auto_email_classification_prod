# SES Module - IMAP-based Email Receiving
# SES is only used for SENDING emails (responses)
# Gmail IMAP is used for RECEIVING emails

locals {
  resource_prefix = "${var.project_name}-${var.environment}"
}

# SES Email Identity (for sending emails only)
resource "aws_ses_email_identity" "support_email" {
  count = var.support_email != "" ? 1 : 0
  email = var.support_email
}

# CloudWatch Log Group for SES sending
resource "aws_cloudwatch_log_group" "ses_logs" {
  name              = "/aws/ses/${local.resource_prefix}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Data source for current AWS account
data "aws_caller_identity" "current" {}

# Note: All SES receiving resources removed (SNS, receipt rules, etc.)
# Email receiving is now handled by Gmail IMAP poller Lambda
