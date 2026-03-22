variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "step_functions_role_arn" {
  description = "ARN of the Step Functions execution role"
  type        = string
}

variable "email_parser_lambda_arn" {
  description = "ARN of the email parser Lambda function"
  type        = string
}

variable "rag_retrieval_lambda_arn" {
  description = "ARN of the RAG retrieval Lambda function"
  type        = string
}

variable "llm_response_lambda_arn" {
  description = "ARN of the LLM response Lambda function"
  type        = string
}

variable "classify_intent_by_llm_lambda_arn" {
  description = "ARN of the LLM intent classification Lambda function"
  type        = string
}

variable "classify_intent_by_biobert_lambda_arn" {
  description = "ARN of the BioBERT intent classification Lambda function"
  type        = string
}

variable "email_sender_lambda_arn" {
  description = "ARN of the email sender Lambda function"
  type        = string
}

variable "crm_validation_lambda_arn" {
  description = "ARN of the CRM validation Lambda function"
  type        = string
}

variable "save_result_lambda_arn" {
  description = "ARN of the save result Lambda function"
  type        = string
}

variable "tags" {
  description = "Common tags for resources"
  type        = map(string)
}
