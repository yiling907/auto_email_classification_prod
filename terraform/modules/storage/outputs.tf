# S3 bucket outputs
output "email_bucket_name" {
  description = "Name of the email S3 bucket"
  value       = aws_s3_bucket.emails.id
}

output "email_bucket_arn" {
  description = "ARN of the email S3 bucket"
  value       = aws_s3_bucket.emails.arn
}

output "knowledge_base_bucket_name" {
  description = "Name of the knowledge base S3 bucket"
  value       = aws_s3_bucket.knowledge_base.id
}

output "knowledge_base_bucket_arn" {
  description = "ARN of the knowledge base S3 bucket"
  value       = aws_s3_bucket.knowledge_base.arn
}

output "logs_bucket_name" {
  description = "Name of the logs S3 bucket"
  value       = aws_s3_bucket.logs.id
}

output "logs_bucket_arn" {
  description = "ARN of the logs S3 bucket"
  value       = aws_s3_bucket.logs.arn
}

# DynamoDB table outputs
output "email_table_name" {
  description = "Name of the email processing DynamoDB table"
  value       = aws_dynamodb_table.email_processing.name
}

output "email_table_arn" {
  description = "ARN of the email processing DynamoDB table"
  value       = aws_dynamodb_table.email_processing.arn
}

output "model_metrics_table_name" {
  description = "Name of the model metrics DynamoDB table"
  value       = aws_dynamodb_table.model_metrics.name
}

output "model_metrics_table_arn" {
  description = "ARN of the model metrics DynamoDB table"
  value       = aws_dynamodb_table.model_metrics.arn
}

output "embeddings_table_name" {
  description = "Name of the embeddings DynamoDB table"
  value       = aws_dynamodb_table.embeddings.name
}

output "embeddings_table_arn" {
  description = "ARN of the embeddings DynamoDB table"
  value       = aws_dynamodb_table.embeddings.arn
}
