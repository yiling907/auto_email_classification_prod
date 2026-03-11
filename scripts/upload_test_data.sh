#!/usr/bin/env bash
set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# InsureMail AI - Upload Test Data Script

echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}   InsureMail AI — Upload Test Data${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEST_DATA_DIR="$PROJECT_ROOT/tests/test_data"

# Get bucket names from Terraform outputs
cd "$PROJECT_ROOT/terraform"

EMAIL_BUCKET=$(terraform output -raw email_bucket_name 2>/dev/null)
KB_BUCKET=$(terraform output -raw knowledge_base_bucket_name 2>/dev/null)

if [ -z "$EMAIL_BUCKET" ] || [ -z "$KB_BUCKET" ]; then
    echo -e "${RED}ERROR: Could not get bucket names from Terraform outputs${NC}"
    echo "Please run terraform apply first"
    exit 1
fi

echo "Email Bucket:          $EMAIL_BUCKET"
echo "Knowledge Base Bucket: $KB_BUCKET"
echo ""

# Upload knowledge base documents
if [ ! -d "$TEST_DATA_DIR/knowledge_base" ]; then
    echo -e "${YELLOW}⚠ Warning: $TEST_DATA_DIR/knowledge_base not found. Skipping knowledge base upload.${NC}"
else
    echo "Uploading knowledge base documents..."
    echo "Test data directory: $TEST_DATA_DIR"

    aws s3 cp "$TEST_DATA_DIR/knowledge_base/" "s3://$KB_BUCKET/knowledge_base/" --recursive

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Knowledge base documents uploaded${NC}"
    else
        echo -e "${RED}✗ Failed to upload knowledge base documents${NC}"
        exit 1
    fi

    echo ""
    echo "Waiting 10 seconds for RAG ingestion to process..."
    sleep 10
fi

# Upload sample emails
echo ""
if [ ! -d "$TEST_DATA_DIR/sample_emails" ]; then
    echo -e "${YELLOW}⚠ Warning: $TEST_DATA_DIR/sample_emails not found. Skipping sample emails upload.${NC}"
else
    echo "Uploading sample emails..."

    aws s3 cp "$TEST_DATA_DIR/sample_emails/" "s3://$EMAIL_BUCKET/emails/" --recursive

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Sample emails uploaded${NC}"
    else
        echo -e "${RED}✗ Failed to upload sample emails${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${GREEN}Test Data Upload Complete!${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo ""
echo "Uploaded:"
echo "- Knowledge base documents (if present)"
echo "- Sample emails (if present)"
echo ""
echo "The email parser Lambda should automatically trigger."
echo "Check CloudWatch Logs for processing status."
echo ""
