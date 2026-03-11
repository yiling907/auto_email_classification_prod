output "email_parser_arn" {
  description = "ARN of the email parser Lambda function"
  value       = aws_lambda_function.email_parser.arn
}

output "email_parser_name" {
  description = "Name of the email parser Lambda function"
  value       = aws_lambda_function.email_parser.function_name
}

output "rag_ingestion_arn" {
  description = "ARN of the RAG ingestion Lambda function"
  value       = aws_lambda_function.rag_ingestion.arn
}

output "rag_ingestion_name" {
  description = "Name of the RAG ingestion Lambda function"
  value       = aws_lambda_function.rag_ingestion.function_name
}

output "rag_retrieval_arn" {
  description = "ARN of the RAG retrieval Lambda function"
  value       = aws_lambda_function.rag_retrieval.arn
}

output "rag_retrieval_name" {
  description = "Name of the RAG retrieval Lambda function"
  value       = aws_lambda_function.rag_retrieval.function_name
}

output "claude_response_arn" {
  description = "ARN of the Claude response Lambda function"
  value       = aws_lambda_function.claude_response.arn
}

output "claude_response_name" {
  description = "Name of the Claude response Lambda function"
  value       = aws_lambda_function.claude_response.function_name
}

output "classify_intent_arn" {
  description = "ARN of the multi-LLM inference Lambda function"
  value       = aws_lambda_function.classify_intent.arn
}

output "classify_intent_name" {
  description = "Name of the multi-LLM inference Lambda function"
  value       = aws_lambda_function.classify_intent.function_name
}

output "api_handlers_arn" {
  description = "ARN of the API handlers Lambda function"
  value       = aws_lambda_function.api_handlers.arn
}

output "api_handlers_name" {
  description = "Name of the API handlers Lambda function"
  value       = aws_lambda_function.api_handlers.function_name
}

output "gmail_imap_poller_arn" {
  description = "ARN of the Gmail IMAP poller Lambda function"
  value       = aws_lambda_function.gmail_imap_poller.arn
}

output "gmail_imap_poller_name" {
  description = "Name of the Gmail IMAP poller Lambda function"
  value       = aws_lambda_function.gmail_imap_poller.function_name
}


output "email_sender_arn" {
  description = "ARN of the email sender Lambda function"
  value       = aws_lambda_function.email_sender.arn
}

output "email_sender_name" {
  description = "Name of the email sender Lambda function"
  value       = aws_lambda_function.email_sender.function_name
}

output "email_parser_lambda_permission_id" {
  description = "ID of the S3 permission for email parser Lambda"
  value       = aws_lambda_permission.allow_s3_email_parser.id
}

output "rag_ingestion_lambda_permission_id" {
  description = "ID of the S3 permission for RAG ingestion Lambda"
  value       = aws_lambda_permission.allow_s3_rag_ingestion.id
}
