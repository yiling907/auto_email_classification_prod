# EventBridge Rules for Periodic Tasks

# Daily metrics calculation (runs at 9:00 AM UTC)
resource "aws_cloudwatch_event_rule" "daily_metrics" {
  name                = "${var.project_name}-${var.environment}-daily-metrics"
  description         = "Trigger daily model metrics calculation"
  schedule_expression = "cron(0 9 * * ? *)"  # 9:00 AM UTC daily

  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-daily-metrics"
  })
}

resource "aws_cloudwatch_event_target" "evaluation_metrics" {
  rule      = aws_cloudwatch_event_rule.daily_metrics.name
  target_id = "EvaluationMetricsLambda"
  arn       = var.evaluation_metrics_lambda_arn

  input = jsonencode({
    task_type = "all"
    days      = 7
  })
}

resource "aws_lambda_permission" "allow_eventbridge_daily_metrics" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = var.evaluation_metrics_lambda_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_metrics.arn
}

# Weekly comprehensive report (runs Sunday at 00:00 UTC)
resource "aws_cloudwatch_event_rule" "weekly_report" {
  name                = "${var.project_name}-${var.environment}-weekly-report"
  description         = "Trigger weekly comprehensive metrics report"
  schedule_expression = "cron(0 0 ? * SUN *)"  # Midnight UTC every Sunday

  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-weekly-report"
  })
}

resource "aws_cloudwatch_event_target" "weekly_evaluation_metrics" {
  rule      = aws_cloudwatch_event_rule.weekly_report.name
  target_id = "WeeklyEvaluationMetrics"
  arn       = var.evaluation_metrics_lambda_arn

  input = jsonencode({
    task_type = "all"
    days      = 30
  })
}

resource "aws_lambda_permission" "allow_eventbridge_weekly_report" {
  statement_id  = "AllowExecutionFromEventBridgeWeekly"
  action        = "lambda:InvokeFunction"
  function_name = var.evaluation_metrics_lambda_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_report.arn
}

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
