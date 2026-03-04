#!/bin/bash
set -e

# InsureMail AI - Terraform Deployment Script

echo "========================================="
echo "InsureMail AI - Terraform Deployment"
echo "========================================="

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v terraform &> /dev/null; then
    echo "ERROR: Terraform is not installed"
    exit 1
fi

if ! command -v aws &> /dev/null; then
    echo "ERROR: AWS CLI is not installed"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo "ERROR: AWS credentials not configured"
    exit 1
fi

echo "✓ Prerequisites check passed"
echo ""

# Navigate to terraform directory
cd "$(dirname "$0")/../terraform"

# Initialize Terraform
echo "Initializing Terraform..."
terraform init

# Validate configuration
echo ""
echo "Validating Terraform configuration..."
terraform validate

if [ $? -ne 0 ]; then
    echo "ERROR: Terraform validation failed"
    exit 1
fi

echo "✓ Terraform validation passed"
echo ""

# Plan deployment
echo "Creating Terraform plan..."
terraform plan -out=tfplan

echo ""
echo "========================================="
echo "Review the plan above."
echo "========================================="
echo ""

read -p "Do you want to apply this plan? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Deployment cancelled"
    rm -f tfplan
    exit 0
fi

# Apply deployment
echo ""
echo "Applying Terraform configuration..."
terraform apply tfplan

rm -f tfplan

echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
echo ""

# Show outputs
echo "Terraform Outputs:"
terraform output

echo ""
echo "Next Steps:"
echo "1. Enable Bedrock model access in AWS Console"
echo "2. Upload test data: ./scripts/upload_test_data.sh"
echo "3. Test the pipeline: ./scripts/test_pipeline.sh"
echo ""
