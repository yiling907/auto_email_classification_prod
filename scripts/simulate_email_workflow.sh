#!/usr/bin/env bash

# Script to simulate complete email workflow for testing
# Use this when you can't send emails via SES (e.g., Gmail to Gmail)

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   InsureMail AI - Email Workflow Simulator${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

# Get State Machine ARN
STATE_MACHINE_ARN=$(aws stepfunctions list-state-machines --query 'stateMachines[?contains(name, `insuremail-ai-dev-email-processing`)].stateMachineArn' --output text)

if [ -z "$STATE_MACHINE_ARN" ]; then
    echo -e "${RED}✗ State machine not found${NC}"
    exit 1
fi

echo -e "${GREEN}State Machine: ${STATE_MACHINE_ARN}${NC}"
echo

# Prompt for email details
read -p "From email (default: customer@example.com): " FROM_EMAIL
FROM_EMAIL=${FROM_EMAIL:-customer@example.com}

read -p "To email (default: support@yourdomain.com): " TO_EMAIL
TO_EMAIL=${TO_EMAIL:-support@yourdomain.com}

read -p "Subject (default: Question about my claim): " SUBJECT
SUBJECT=${SUBJECT:-Question about my claim}

echo
echo "Email body (press Ctrl+D when done):"
EMAIL_BODY=$(cat)

if [ -z "$EMAIL_BODY" ]; then
    EMAIL_BODY="I submitted a claim last week for policy #12345. What is the status? I need help with my claim processing."
fi

# Generate unique execution name
EXECUTION_NAME="test-email-$(date +%s)"

# Create email file
EMAIL_FILE="/tmp/${EXECUTION_NAME}.eml"
cat > "$EMAIL_FILE" <<EOF
From: $FROM_EMAIL
To: $TO_EMAIL
Subject: $SUBJECT
Date: $(date -u +"%a, %d %b %Y %H:%M:%S +0000")
Message-ID: <${EXECUTION_NAME}@test.local>

$EMAIL_BODY
EOF

echo
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Step 1: Upload Email to S3${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

# Upload to S3
S3_KEY="incoming/${EXECUTION_NAME}"
aws s3 cp "$EMAIL_FILE" "s3://insuremail-ai-dev-emails/${S3_KEY}"

echo -e "${GREEN}✓ Email uploaded to S3: ${S3_KEY}${NC}"
echo

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Step 2: Trigger Step Functions${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

# Create Step Functions input
SF_INPUT=$(cat <<EOF_JSON
{
  "Records": [{
    "eventSource": "aws:sns",
    "Sns": {
      "Message": "{\"notificationType\":\"Received\",\"receipt\":{\"action\":{\"type\":\"S3\",\"bucketName\":\"insuremail-ai-dev-emails\",\"objectKey\":\"${S3_KEY}\"}}}}"
    }
  }]
}
EOF_JSON
)

# Start execution
EXECUTION_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --name "$EXECUTION_NAME" \
  --input "$SF_INPUT" \
  --query 'executionArn' \
  --output text)

echo -e "${GREEN}✓ Step Functions execution started${NC}"
echo -e "  Execution ARN: ${EXECUTION_ARN}"
echo

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Step 3: Monitor Execution${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

echo "Waiting for execution to complete..."
echo

# Poll execution status
while true; do
    STATUS=$(aws stepfunctions describe-execution \
        --execution-arn "$EXECUTION_ARN" \
        --query 'status' \
        --output text)

    if [ "$STATUS" == "SUCCEEDED" ]; then
        echo -e "${GREEN}✓ Execution SUCCEEDED${NC}"
        break
    elif [ "$STATUS" == "FAILED" ] || [ "$STATUS" == "TIMED_OUT" ] || [ "$STATUS" == "ABORTED" ]; then
        echo -e "${RED}✗ Execution ${STATUS}${NC}"
        break
    else
        echo -n "."
        sleep 2
    fi
done

echo

# Get execution output
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Execution Result${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

aws stepfunctions describe-execution \
    --execution-arn "$EXECUTION_ARN" \
    --query 'output' \
    --output text | jq '.' || echo "No output"

echo
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Check Results${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

echo -e "${YELLOW}View execution details:${NC}"
echo "  aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN | jq '.'"
echo

echo -e "${YELLOW}View CloudWatch logs:${NC}"
echo "  aws logs tail /aws/lambda/insuremail-ai-dev-email-parser --since 5m"
echo "  aws logs tail /aws/lambda/insuremail-ai-dev-multi-llm-inference --since 5m"
echo "  aws logs tail /aws/lambda/insuremail-ai-dev-claude-response --since 5m"
echo

echo -e "${YELLOW}Check DynamoDB metrics:${NC}"
echo "  aws dynamodb scan --table-name insuremail-ai-dev-model-metrics --max-items 5"
echo

echo -e "${GREEN}✓ Workflow simulation complete!${NC}"
