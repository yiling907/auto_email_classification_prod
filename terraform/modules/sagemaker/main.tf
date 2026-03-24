# SageMaker module — Serverless inference endpoint for PyTorch model
# Serverless inference: pay per invocation, no idle cost (vs ml.g5.xlarge ~$1.41/hr always-on)

locals {
  resource_prefix = "${var.project_name}-${var.environment}"

  # HuggingFace PyTorch CPU DLC — serverless does not support GPU instances
  pytorch_dlc_image = "763104351884.dkr.ecr.${var.aws_region}.amazonaws.com/huggingface-pytorch-inference:2.1.0-transformers4.37.0-cpu-py310-ubuntu22.04"

  # S3 path where upload_model.py puts model.tar.gz
  model_data_url = "s3://${aws_s3_bucket.model_artifacts.bucket}/model/model.tar.gz"
}

# ─── S3 bucket for model artifacts ───────────────────────────────────────────
resource "aws_s3_bucket" "model_artifacts" {
  bucket = "${local.resource_prefix}-model-artifacts"
  tags   = merge(var.tags, { Name = "${local.resource_prefix}-model-artifacts" })
}

resource "aws_s3_bucket_versioning" "model_artifacts" {
  bucket = aws_s3_bucket.model_artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "model_artifacts" {
  bucket = aws_s3_bucket.model_artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "model_artifacts" {
  bucket                  = aws_s3_bucket.model_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ─── IAM role for SageMaker ───────────────────────────────────────────────────
resource "aws_iam_role" "sagemaker_execution" {
  name = "${local.resource_prefix}-sagemaker-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
    }]
  })

  tags = merge(var.tags, { Name = "${local.resource_prefix}-sagemaker-execution" })
}

# SageMaker needs broad access to CloudWatch, ECR, and S3 for model hosting
resource "aws_iam_role_policy_attachment" "sagemaker_full_access" {
  role       = aws_iam_role.sagemaker_execution.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

# Explicit S3 read access for model artifacts bucket
resource "aws_iam_role_policy" "sagemaker_s3_read" {
  name = "${local.resource_prefix}-sagemaker-s3-read"
  role = aws_iam_role.sagemaker_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.model_artifacts.arn,
        "${aws_s3_bucket.model_artifacts.arn}/*"
      ]
    }]
  })
}

# ─── SageMaker Model ──────────────────────────────────────────────────────────
resource "aws_sagemaker_model" "pytorch" {
  name               = "${local.resource_prefix}-pytorch-model"
  execution_role_arn = aws_iam_role.sagemaker_execution.arn

  primary_container {
    # PyTorch GPU Deep Learning Container
    image          = local.pytorch_dlc_image
    # model.tar.gz uploaded by scripts/upload_model.py
    model_data_url = local.model_data_url

    environment = {
      # SageMaker will call inference.py inside the tarball
      SAGEMAKER_PROGRAM        = "inference.py"
      SAGEMAKER_SUBMIT_DIRECTORY = "/opt/ml/model"
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-pytorch-model" })
}

# ─── SageMaker Endpoint Configuration ────────────────────────────────────────
resource "aws_sagemaker_endpoint_configuration" "pytorch" {
  name = "${local.resource_prefix}-pytorch-endpoint-config"

  production_variants {
    variant_name = "primary"
    model_name   = aws_sagemaker_model.pytorch.name

    # Serverless inference — no instance to provision, billed per invocation only
    # Cost: ~$0.20/million inference + $0.20/GB-s compute (vs ml.g5.xlarge $1.41/hr always-on)
    # Cold start: ~60-90s if idle; warm requests ~2-5s on CPU
    serverless_config {
      memory_size_in_mb = 3072   # account quota limit is 3072 MB
      max_concurrency   = 5      # matches assessment script --concurrency default
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-pytorch-endpoint-config" })
}

# ─── SageMaker Endpoint ───────────────────────────────────────────────────────
resource "aws_sagemaker_endpoint" "pytorch" {
  name                 = "${local.resource_prefix}-pytorch-endpoint"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.pytorch.name

  tags = merge(var.tags, { Name = "${local.resource_prefix}-pytorch-endpoint" })
  # Note: serverless endpoint creation takes ~3-5 minutes
}
