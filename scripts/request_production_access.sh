#!/bin/bash

# SES Production Access Request Helper
# This script helps you request production access for Amazon SES

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   SES Production Access Request${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

echo -e "${YELLOW}Why move to production access?${NC}"
echo "• Send emails to ANY address (no verification needed)"
echo "• Higher sending limits (50,000 emails/day)"
echo "• No restrictions on recipient addresses"
echo

echo -e "${YELLOW}Current SES Status:${NC}"
PRODUCTION_ACCESS=$(aws sesv2 get-account --query 'ProductionAccess' --output text 2>/dev/null || echo "false")
SENDING_ENABLED=$(aws sesv2 get-account --query 'SendingEnabled' --output text 2>/dev/null || echo "false")

if [ "$PRODUCTION_ACCESS" = "true" ]; then
    echo -e "${GREEN}✓ Production Access: ENABLED${NC}"
else
    echo -e "${YELLOW}⚠ Production Access: SANDBOX MODE${NC}"
fi

if [ "$SENDING_ENABLED" = "true" ]; then
    echo -e "${GREEN}✓ Sending: ENABLED${NC}"
else
    echo -e "${RED}✗ Sending: DISABLED${NC}"
fi

echo

if [ "$PRODUCTION_ACCESS" != "true" ]; then
    echo -e "${YELLOW}To request production access:${NC}"
    echo
    echo "1. Go to AWS Console: https://console.aws.amazon.com/ses/"
    echo "2. Click 'Account Dashboard' in the left sidebar"
    echo "3. Look for 'Sending statistics' section"
    echo "4. Click 'Request production access' button"
    echo
    echo "5. Fill out the request form:"
    echo "   • Mail type: Transactional"
    echo "   • Website URL: Your company website (or GitHub repo)"
    echo "   • Use case description:"
    echo
    echo -e "${BLUE}─────────────────────────────────────────────${NC}"
    cat << 'REQUEST'
We are building an AI-powered automated email response system for
insurance customer service. Our system:

- Receives customer emails (claims inquiries, policy questions)
- Uses AWS Bedrock AI models to classify intent and extract entities
- Generates high-confidence automated responses using RAG
- Sends professional email responses to customers

Email Types:
- Transactional responses to customer inquiries
- Claim status updates
- Policy information responses

Expected Volume: 1,000-5,000 emails per day

Compliance:
- All responses include unsubscribe mechanisms
- No marketing emails
- GDPR/compliance-focused architecture
- Full audit logging

Bounce/Complaint Handling:
- Automated bounce processing via SNS
- Complaint feedback loop configured
- Regular monitoring of email metrics
REQUEST
    echo -e "${BLUE}─────────────────────────────────────────────${NC}"
    echo
    echo "6. Submit the request"
    echo "7. AWS usually responds within 24-48 hours"
    echo
    echo -e "${GREEN}Tip:${NC} AWS approval is faster if you:"
    echo "   • Have a verified domain (not just email)"
    echo "   • Provide a clear, legitimate use case"
    echo "   • Show compliance awareness"
    echo
else
    echo -e "${GREEN}✓ You already have production access!${NC}"
    echo "You can now send emails to any address without verification."
fi

echo
echo -e "${YELLOW}Current Verified Identities:${NC}"
aws ses list-identities --identity-type EmailAddress --output table 2>/dev/null || echo "No verified emails"

echo
echo -e "${YELLOW}Need to verify more emails while in sandbox?${NC}"
echo "Run: aws ses verify-email-identity --email-address YOUR_EMAIL@example.com"
