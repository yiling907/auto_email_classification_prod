#!/usr/bin/env bash
set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# InsureMail AI - Terraform Deployment Script

echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}   InsureMail AI — Terraform Deployment${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v terraform &> /dev/null; then
    echo -e "${RED}ERROR: Terraform is not installed${NC}"
    exit 1
fi

if ! command -v aws &> /dev/null; then
    echo -e "${RED}ERROR: AWS CLI is not installed${NC}"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}ERROR: AWS credentials not configured${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Prerequisites check passed${NC}"
echo ""

# Get project root and navigate to terraform directory
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT/terraform"

# Initialize Terraform
echo "Initializing Terraform..."
terraform init

# Validate configuration
echo ""
echo "Validating Terraform configuration..."
terraform validate

if [ $? -ne 0 ]; then
    echo -e "${RED}ERROR: Terraform validation failed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Terraform validation passed${NC}"
echo ""

# Plan deployment
echo "Creating Terraform plan..."
terraform plan -out=tfplan

echo ""
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}   Review the plan above.${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
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
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
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
