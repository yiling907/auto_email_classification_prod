# API Gateway module - REST API for dashboard

locals {
  resource_prefix = "${var.project_name}-${var.environment}"
}

# API Gateway REST API
resource "aws_api_gateway_rest_api" "dashboard_api" {
  name        = "${local.resource_prefix}-dashboard-api"
  description = "API for InsureMail AI Dashboard"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-dashboard-api" })
}

# API Gateway Resource - /api
resource "aws_api_gateway_resource" "api" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  parent_id   = aws_api_gateway_rest_api.dashboard_api.root_resource_id
  path_part   = "api"
}

# API Gateway Resource - /api/{proxy+}
resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  parent_id   = aws_api_gateway_resource.api.id
  path_part   = "{proxy+}"
}

# API Gateway Method - ANY /api/{proxy+}
resource "aws_api_gateway_method" "proxy" {
  rest_api_id   = aws_api_gateway_rest_api.dashboard_api.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "ANY"
  authorization = "NONE"
}

# API Gateway Integration with Lambda
resource "aws_api_gateway_integration" "lambda" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:aws:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${var.api_handler_lambda_arn}/invocations"
}

# API Gateway Method - OPTIONS /api/{proxy+} for CORS
resource "aws_api_gateway_method" "proxy_options" {
  rest_api_id   = aws_api_gateway_rest_api.dashboard_api.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

# API Gateway Integration - OPTIONS for CORS
resource "aws_api_gateway_integration" "proxy_options" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method

  type = "MOCK"

  request_templates = {
    "application/json" = jsonencode({
      statusCode = 200
    })
  }
}

# API Gateway Method Response - OPTIONS
resource "aws_api_gateway_method_response" "proxy_options" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }

  response_models = {
    "application/json" = "Empty"
  }
}

# API Gateway Integration Response - OPTIONS
resource "aws_api_gateway_integration_response" "proxy_options" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  status_code = aws_api_gateway_method_response.proxy_options.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,OPTIONS,POST,PUT'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  depends_on = [aws_api_gateway_integration.proxy_options]
}

# ─── /api/model/inference — SageMaker GPU inference endpoint ─────────────────

# /api/model  resource
resource "aws_api_gateway_resource" "model" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  parent_id   = aws_api_gateway_resource.api.id
  path_part   = "model"
}

# /api/model/inference  resource
resource "aws_api_gateway_resource" "model_inference" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  parent_id   = aws_api_gateway_resource.model.id
  path_part   = "inference"
}

# POST /api/model/inference
resource "aws_api_gateway_method" "model_inference_post" {
  rest_api_id   = aws_api_gateway_rest_api.dashboard_api.id
  resource_id   = aws_api_gateway_resource.model_inference.id
  http_method   = "POST"
  authorization = "NONE"
}

# Integration: POST → sagemaker_inference Lambda (AWS_PROXY)
resource "aws_api_gateway_integration" "model_inference" {
  rest_api_id             = aws_api_gateway_rest_api.dashboard_api.id
  resource_id             = aws_api_gateway_resource.model_inference.id
  http_method             = aws_api_gateway_method.model_inference_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:aws:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${var.sagemaker_inference_lambda_arn}/invocations"
}

# OPTIONS /api/model/inference — CORS preflight
resource "aws_api_gateway_method" "model_inference_options" {
  rest_api_id   = aws_api_gateway_rest_api.dashboard_api.id
  resource_id   = aws_api_gateway_resource.model_inference.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "model_inference_options" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  resource_id = aws_api_gateway_resource.model_inference.id
  http_method = aws_api_gateway_method.model_inference_options.http_method
  type        = "MOCK"
  request_templates = { "application/json" = jsonencode({ statusCode = 200 }) }
}

resource "aws_api_gateway_method_response" "model_inference_options" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  resource_id = aws_api_gateway_resource.model_inference.id
  http_method = aws_api_gateway_method.model_inference_options.http_method
  status_code = "200"
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
  response_models = { "application/json" = "Empty" }
}

resource "aws_api_gateway_integration_response" "model_inference_options" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  resource_id = aws_api_gateway_resource.model_inference.id
  http_method = aws_api_gateway_method.model_inference_options.http_method
  status_code = aws_api_gateway_method_response.model_inference_options.status_code
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
  depends_on = [aws_api_gateway_integration.model_inference_options]
}

# Lambda permission — allow API Gateway to invoke sagemaker_inference Lambda
resource "aws_lambda_permission" "sagemaker_inference" {
  statement_id  = "AllowAPIGatewaySageMakerInference"
  action        = "lambda:InvokeFunction"
  function_name = var.sagemaker_inference_lambda_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.dashboard_api.execution_arn}/*/*"
}

# API Gateway Deployment
resource "aws_api_gateway_deployment" "dashboard" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.api.id,
      aws_api_gateway_resource.proxy.id,
      aws_api_gateway_method.proxy.id,
      aws_api_gateway_integration.lambda.id,
      aws_api_gateway_resource.model_inference.id,
      aws_api_gateway_integration.model_inference.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.lambda,
    aws_api_gateway_integration.proxy_options,
    aws_api_gateway_integration.model_inference,
    aws_api_gateway_integration.model_inference_options,
  ]
}

# API Gateway Stage
resource "aws_api_gateway_stage" "dashboard" {
  deployment_id = aws_api_gateway_deployment.dashboard.id
  rest_api_id   = aws_api_gateway_rest_api.dashboard_api.id
  stage_name    = var.environment

  tags = merge(var.tags, { Name = "${local.resource_prefix}-api-stage" })
}

# Lambda Permission for API Gateway
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.api_handler_lambda_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.dashboard_api.execution_arn}/*/*"
}

# Data source for current region
data "aws_region" "current" {}
