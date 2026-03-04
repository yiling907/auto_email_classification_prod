output "dashboard_name" {
  description = "Name of the CloudWatch dashboard"
  value       = aws_cloudwatch_dashboard.main.dashboard_name
}

output "step_functions_alarm_arn" {
  description = "ARN of the Step Functions failure alarm"
  value       = aws_cloudwatch_metric_alarm.step_functions_failures.arn
}

output "lambda_errors_alarm_arn" {
  description = "ARN of the Lambda errors alarm"
  value       = aws_cloudwatch_metric_alarm.lambda_errors.arn
}
