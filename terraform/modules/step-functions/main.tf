# Step Functions module - Email processing workflow

locals {
  resource_prefix = "${var.project_name}-${var.environment}"
}

# Read the state machine definition template
locals {
  state_machine_definition = templatefile(
    "${path.root}/../step-functions/email_processing_workflow.json",
    {
      email_parser_lambda_arn        = var.email_parser_lambda_arn
      rag_retrieval_lambda_arn       = var.rag_retrieval_lambda_arn
      claude_response_lambda_arn     = var.claude_response_lambda_arn
      multi_llm_inference_lambda_arn = var.multi_llm_inference_lambda_arn
    }
  )
}

# CloudWatch Log Group for Step Functions (must be created first)
resource "aws_cloudwatch_log_group" "step_functions" {
  name              = "/aws/vendedlogs/states/${local.resource_prefix}-email-processing"
  retention_in_days = 7
  tags              = var.tags
}

# Step Functions state machine
resource "aws_sfn_state_machine" "email_processing" {
  name     = "${local.resource_prefix}-email-processing"
  role_arn = var.step_functions_role_arn

  definition = local.state_machine_definition

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tracing_configuration {
    enabled = true
  }

  depends_on = [aws_cloudwatch_log_group.step_functions]

  tags = merge(var.tags, { Name = "${local.resource_prefix}-email-processing" })
}
