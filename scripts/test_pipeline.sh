#!/bin/bash
set -e

# InsureMail AI - Test Pipeline Script

echo "========================================="
echo "InsureMail AI - Test Pipeline"
echo "========================================="

# Get resources from Terraform outputs
cd "$(dirname "$0")/../terraform"

STATE_MACHINE_ARN=$(terraform output -raw state_machine_arn 2>/dev/null)
EMAIL_TABLE=$(terraform output -raw email_table_name 2>/dev/null)

if [ -z "$STATE_MACHINE_ARN" ] || [ -z "$EMAIL_TABLE" ]; then
    echo "ERROR: Could not get resources from Terraform outputs"
    echo "Please run terraform apply first"
    exit 1
fi

echo "State Machine: $STATE_MACHINE_ARN"
echo "Email Table: $EMAIL_TABLE"
echo ""

# Test 1: Check if knowledge base has embeddings
echo "Test 1: Checking knowledge base..."
EMBEDDINGS_TABLE=$(terraform output -raw embeddings_table_name 2>/dev/null)
EMBEDDING_COUNT=$(aws dynamodb scan --table-name "$EMBEDDINGS_TABLE" --select "COUNT" --query "Count" --output text 2>/dev/null || echo "0")

echo "Knowledge base documents: $EMBEDDING_COUNT"

if [ "$EMBEDDING_COUNT" -gt 0 ]; then
    echo "✓ Knowledge base is populated"
else
    echo "⚠ Knowledge base is empty. Run ./scripts/upload_test_data.sh first"
fi

echo ""

# Test 2: Check if emails were parsed
echo "Test 2: Checking parsed emails..."
EMAIL_COUNT=$(aws dynamodb scan --table-name "$EMAIL_TABLE" --select "COUNT" --query "Count" --output text 2>/dev/null || echo "0")

echo "Parsed emails: $EMAIL_COUNT"

if [ "$EMAIL_COUNT" -gt 0 ]; then
    echo "✓ Emails have been parsed"

    # Show sample email
    echo ""
    echo "Sample email record:"
    aws dynamodb scan --table-name "$EMAIL_TABLE" --limit 1 --output json | jq '.Items[0]' || echo "Could not retrieve email"
else
    echo "⚠ No emails found. Upload test emails first"
fi

echo ""

# Test 3: Manually trigger Step Functions
echo "Test 3: Testing Step Functions workflow..."
read -p "Do you want to trigger the workflow manually? (yes/no): " TRIGGER

if [ "$TRIGGER" = "yes" ]; then
    # Create test input
    TEST_INPUT=$(cat <<EOF
{
  "bucket": "$(terraform output -raw email_bucket_name)",
  "key": "emails/claim_inquiry_001.txt"
}
EOF
)

    echo "Starting execution..."
    EXECUTION_ARN=$(aws stepfunctions start-execution \
        --state-machine-arn "$STATE_MACHINE_ARN" \
        --input "$TEST_INPUT" \
        --query "executionArn" \
        --output text)

    echo "Execution started: $EXECUTION_ARN"
    echo ""
    echo "Monitor progress:"
    echo "aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN"
    echo ""
    echo "Or view in AWS Console:"
    echo "https://console.aws.amazon.com/states/home"
fi

echo ""
echo "========================================="
echo "Test Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Check CloudWatch Logs: /aws/lambda/ and /aws/vendedlogs/states/"
echo "2. View CloudWatch Dashboard in AWS Console"
echo "3. Query DynamoDB tables for results"
echo ""
