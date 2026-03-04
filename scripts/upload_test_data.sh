#!/bin/bash
set -e

# InsureMail AI - Upload Test Data Script

echo "========================================="
echo "InsureMail AI - Upload Test Data"
echo "========================================="

# Get bucket names from Terraform outputs
cd "$(dirname "$0")/../terraform"

EMAIL_BUCKET=$(terraform output -raw email_bucket_name 2>/dev/null)
KB_BUCKET=$(terraform output -raw knowledge_base_bucket_name 2>/dev/null)

if [ -z "$EMAIL_BUCKET" ] || [ -z "$KB_BUCKET" ]; then
    echo "ERROR: Could not get bucket names from Terraform outputs"
    echo "Please run terraform apply first"
    exit 1
fi

echo "Email Bucket: $EMAIL_BUCKET"
echo "Knowledge Base Bucket: $KB_BUCKET"
echo ""

# Upload knowledge base documents
echo "Uploading knowledge base documents..."
TEST_DATA_DIR="$(dirname "$0")/../tests/test_data"

aws s3 cp "$TEST_DATA_DIR/knowledge_base/" "s3://$KB_BUCKET/knowledge_base/" --recursive

if [ $? -eq 0 ]; then
    echo "✓ Knowledge base documents uploaded"
else
    echo "✗ Failed to upload knowledge base documents"
    exit 1
fi

echo ""
echo "Waiting 10 seconds for RAG ingestion to process..."
sleep 10

# Upload sample emails
echo ""
echo "Uploading sample emails..."

aws s3 cp "$TEST_DATA_DIR/sample_emails/" "s3://$EMAIL_BUCKET/emails/" --recursive

if [ $? -eq 0 ]; then
    echo "✓ Sample emails uploaded"
else
    echo "✗ Failed to upload sample emails"
    exit 1
fi

echo ""
echo "========================================="
echo "Test Data Upload Complete!"
echo "========================================="
echo ""
echo "Uploaded:"
echo "- 3 knowledge base documents"
echo "- 3 sample emails"
echo ""
echo "The email parser Lambda should automatically trigger."
echo "Check CloudWatch Logs for processing status."
echo ""
