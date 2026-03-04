# SES Module - Email receiving and sending configuration

locals {
  resource_prefix = "${var.project_name}-${var.environment}"
}

# SES Email Identity (for sending emails)
# Note: In production, use domain identity instead of email identity
resource "aws_ses_email_identity" "support_email" {
  count = var.support_email != "" ? 1 : 0
  email = var.support_email
}

# SNS Topic for SES email notifications
resource "aws_sns_topic" "ses_notifications" {
  name = "${local.resource_prefix}-ses-notifications"
  tags = var.tags
}

# SNS Topic Policy to allow SES to publish
resource "aws_sns_topic_policy" "ses_notifications" {
  arn = aws_sns_topic.ses_notifications.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ses.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.ses_notifications.arn
        Condition = {
          StringEquals = {
            "AWS:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# Lambda permission to allow SNS to invoke email receiver
resource "aws_lambda_permission" "allow_sns_email_receiver" {
  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = var.email_receiver_lambda_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.ses_notifications.arn
}

# SNS subscription to Lambda
resource "aws_sns_topic_subscription" "email_receiver" {
  topic_arn = aws_sns_topic.ses_notifications.arn
  protocol  = "lambda"
  endpoint  = var.email_receiver_lambda_arn
}

# SES Receipt Rule Set
resource "aws_ses_receipt_rule_set" "main" {
  rule_set_name = "${local.resource_prefix}-ruleset"
}

# Activate the rule set
resource "aws_ses_active_receipt_rule_set" "main" {
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
}

# SES Receipt Rule - Store emails in S3 and notify via SNS
resource "aws_ses_receipt_rule" "store_and_notify" {
  name          = "${local.resource_prefix}-receive-emails"
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
  recipients    = var.ses_receipt_recipients
  enabled       = true
  scan_enabled  = true

  # First action: Store email in S3
  s3_action {
    bucket_name       = var.email_bucket_name
    object_key_prefix = "incoming/"
    position          = 1
    topic_arn         = aws_sns_topic.ses_notifications.arn
  }

  # Depend on SNS topic policy
  depends_on = [aws_sns_topic_policy.ses_notifications]
}

# S3 bucket policy to allow SES to write emails
resource "aws_s3_bucket_policy" "allow_ses" {
  bucket = var.email_bucket_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowSESPuts"
        Effect = "Allow"
        Principal = {
          Service = "ses.amazonaws.com"
        }
        Action   = "s3:PutObject"
        Resource = "${var.email_bucket_arn}/incoming/*"
        Condition = {
          StringEquals = {
            "AWS:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# Data source for current AWS account
data "aws_caller_identity" "current" {}

# CloudWatch Log Group for SES (for debugging)
resource "aws_cloudwatch_log_group" "ses_logs" {
  name              = "/aws/ses/${local.resource_prefix}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}
