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

output "llm_response_arn" {
  description = "ARN of the LLM response Lambda function"
  value       = aws_lambda_function.llm_response.arn
}

output "llm_response_name" {
  description = "Name of the LLM response Lambda function"
  value       = aws_lambda_function.llm_response.function_name
}

output "classify_intent_by_llm_arn" {
  description = "ARN of the LLM intent classification Lambda function"
  value       = aws_lambda_function.classify_intent_by_llm.arn
}

output "classify_intent_by_llm_name" {
  description = "Name of the LLM intent classification Lambda function"
  value       = aws_lambda_function.classify_intent_by_llm.function_name
}

output "classify_intent_by_biobert_arn" {
  description = "ARN of the BioBERT intent classification Lambda function"
  value       = aws_lambda_function.classify_intent_by_biobert.arn
}

output "classify_intent_by_biobert_name" {
  description = "Name of the BioBERT intent classification Lambda function"
  value       = aws_lambda_function.classify_intent_by_biobert.function_name
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

output "crm_validation_arn" {
  description = "ARN of the CRM validation Lambda function"
  value       = aws_lambda_function.crm_validation.arn
}

output "crm_validation_name" {
  description = "Name of the CRM validation Lambda function"
  value       = aws_lambda_function.crm_validation.function_name
}

output "rag_ingestion_lambda_permission_id" {
  description = "ID of the S3 permission for RAG ingestion Lambda"
  value       = aws_lambda_permission.allow_s3_rag_ingestion.id
}

output "save_result_arn" {
  description = "ARN of the save result Lambda function"
  value       = aws_lambda_function.save_result.arn
}

output "save_result_name" {
  description = "Name of the save result Lambda function"
  value       = aws_lambda_function.save_result.function_name
}

output "sagemaker_inference_arn" {
  description = "ARN of the SageMaker inference Lambda function"
  value       = aws_lambda_function.sagemaker_inference.arn
}

output "sagemaker_inference_name" {
  description = "Name of the SageMaker inference Lambda function"
  value       = aws_lambda_function.sagemaker_inference.function_name
}
