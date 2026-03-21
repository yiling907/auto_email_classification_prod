output "endpoint_name" {
  description = "Name of the SageMaker inference endpoint"
  value       = aws_sagemaker_endpoint.pytorch.name
}

output "endpoint_arn" {
  description = "ARN of the SageMaker inference endpoint"
  value       = aws_sagemaker_endpoint.pytorch.arn
}

output "model_artifacts_bucket_name" {
  description = "Name of the S3 bucket holding model.tar.gz"
  value       = aws_s3_bucket.model_artifacts.bucket
}

output "model_artifacts_bucket_arn" {
  description = "ARN of the S3 bucket holding model.tar.gz"
  value       = aws_s3_bucket.model_artifacts.arn
}
