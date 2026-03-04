# SES Module Outputs

output "sns_topic_arn" {
  description = "ARN of SNS topic for SES notifications"
  value       = aws_sns_topic.ses_notifications.arn
}

output "rule_set_name" {
  description = "Name of the SES receipt rule set"
  value       = aws_ses_receipt_rule_set.main.rule_set_name
}

output "support_email" {
  description = "Support email address configured in SES"
  value       = var.support_email
}

output "ses_identity_arn" {
  description = "ARN of SES email identity (if created)"
  value       = length(aws_ses_email_identity.support_email) > 0 ? aws_ses_email_identity.support_email[0].arn : ""
}
