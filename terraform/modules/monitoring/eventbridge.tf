# EventBridge Rules for Periodic Tasks

# Gmail IMAP Polling Schedule
resource "aws_cloudwatch_event_rule" "gmail_imap_poll" {
  name                = "${var.project_name}-${var.environment}-gmail-imap-poll"
  description         = "Trigger Gmail IMAP poller every 5 minutes"
  schedule_expression = "rate(5 minutes)"
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "gmail_imap_poller" {
  rule      = aws_cloudwatch_event_rule.gmail_imap_poll.name
  target_id = "GmailImapPoller"
  arn       = var.gmail_imap_poller_lambda_arn
}

# Lambda permission to allow EventBridge to invoke Gmail IMAP poller
resource "aws_lambda_permission" "allow_eventbridge_gmail_poll" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = var.gmail_imap_poller_lambda_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.gmail_imap_poll.arn
}
