#!/usr/bin/env bash
set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}   InsureMail AI — Test Pipeline${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo ""

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Get resources from Terraform outputs
cd "$PROJECT_ROOT/terraform"

STATE_MACHINE_ARN=$(terraform output -raw state_machine_arn 2>/dev/null)
EMAIL_TABLE=$(terraform output -raw email_table_name 2>/dev/null)
API_URL=$(terraform output -raw api_gateway_url 2>/dev/null)

if [ -z "$STATE_MACHINE_ARN" ] || [ -z "$EMAIL_TABLE" ]; then
    echo -e "${RED}ERROR: Could not get resources from Terraform outputs${NC}"
    echo "Please run terraform apply first"
    exit 1
fi

echo "State Machine: $STATE_MACHINE_ARN"
echo "Email Table:   $EMAIL_TABLE"
echo ""

# Test 1: Check if knowledge base has embeddings
echo -e "${BLUE}Test 1: Checking knowledge base...${NC}"
EMBEDDINGS_TABLE=$(terraform output -raw embeddings_table_name 2>/dev/null)
EMBEDDING_COUNT=$(aws dynamodb scan --table-name "$EMBEDDINGS_TABLE" --select COUNT --query "Count" --output text 2>/dev/null || echo "0")

echo "Knowledge base embeddings: $EMBEDDING_COUNT"

if [ "$EMBEDDING_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Knowledge base is populated${NC}"
else
    echo -e "${YELLOW}⚠ Knowledge base is empty. Run ./scripts/upload_test_data.sh first${NC}"
fi

echo ""

# Test 2: Check if emails were parsed
echo -e "${BLUE}Test 2: Checking parsed emails...${NC}"
EMAIL_COUNT=$(aws dynamodb scan --table-name "$EMAIL_TABLE" --select COUNT --query "Count" --output text 2>/dev/null || echo "0")

echo "Parsed emails: $EMAIL_COUNT"

if [ "$EMAIL_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Emails have been parsed${NC}"

    # Show sample email
    echo ""
    echo "Sample email record:"
    aws dynamodb scan --table-name "$EMAIL_TABLE" --limit 1 --output json | jq '.Items[0]' || echo "Could not retrieve email"
else
    echo -e "${YELLOW}⚠ No emails found. Upload test emails first${NC}"
fi

echo ""

# Test 3: API health check
echo -e "${BLUE}Test 3: Checking API health...${NC}"
if [ -n "$API_URL" ]; then
    if curl -sf "$API_URL/api/dashboard/overview" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ API health check passed${NC}"
    else
        echo -e "${YELLOW}⚠ API health check failed or returned non-2xx (URL: $API_URL/api/dashboard/overview)${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Could not get API Gateway URL from Terraform outputs${NC}"
fi

echo ""

# Test 4: Manually trigger Step Functions (optional)
echo -e "${BLUE}Test 4: Testing Step Functions workflow...${NC}"
read -p "Do you want to trigger the workflow manually? (yes/no): " TRIGGER

if [ "$TRIGGER" = "yes" ]; then
    # Create test input
    EMAIL_BUCKET=$(terraform output -raw email_bucket_name 2>/dev/null)
    TEST_INPUT=$(cat <<EOF
{
  "bucket": "$EMAIL_BUCKET",
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

    echo -e "${GREEN}✓ Execution started: $EXECUTION_ARN${NC}"
    echo ""
    echo "Monitor progress:"
    echo "  aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN"
    echo ""
    echo "Or view in AWS Console:"
    echo "  https://console.aws.amazon.com/states/home"
fi

echo ""
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${GREEN}Test Complete!${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo ""
echo "Next steps:"
echo "1. Check CloudWatch Logs:"
echo "   aws logs tail /aws/lambda/insuremail-ai-dev-email-parser --follow"
echo "   aws logs tail /aws/lambda/insuremail-ai-dev-multi-llm-inference --follow"
echo "   aws logs tail /aws/lambda/insuremail-ai-dev-claude-response --follow"
echo "2. View CloudWatch Dashboard in AWS Console"
echo "3. Query DynamoDB tables for results"
echo ""
