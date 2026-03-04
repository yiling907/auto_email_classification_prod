# SES Module Outputs (IMAP version - sending only)

output "support_email" {
  description = "Support email address configured in SES"
  value       = var.support_email
}

output "ses_identity_arn" {
  description = "ARN of SES email identity (if created)"
  value       = length(aws_ses_email_identity.support_email) > 0 ? aws_ses_email_identity.support_email[0].arn : ""
}

# REMOVED (no longer exist with IMAP receiving):
# - sns_topic_arn (SNS topic removed)
# - rule_set_name (SES receipt rules removed)
