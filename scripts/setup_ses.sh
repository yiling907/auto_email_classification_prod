#!/bin/bash
set -e

# InsureMail AI - SES Setup Helper Script

echo "========================================="
echo "InsureMail AI - SES Setup"
echo "========================================="
echo ""

# Get project root
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Check if AWS CLI is configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo "ERROR: AWS CLI is not configured or credentials are invalid"
    exit 1
fi

echo "✓ AWS CLI configured"
echo ""

# Prompt for sender email
read -p "Enter sender email address (e.g., support@yourdomain.com): " SENDER_EMAIL

if [ -z "$SENDER_EMAIL" ]; then
    echo "ERROR: Sender email is required"
    exit 1
fi

# Verify email in SES
echo ""
echo "Step 1: Verifying email address in SES..."
echo ""

aws ses verify-email-identity --email-address "$SENDER_EMAIL" 2>/dev/null

if [ $? -eq 0 ]; then
    echo "✓ Verification email sent to $SENDER_EMAIL"
    echo ""
    echo "IMPORTANT: Check your inbox and click the verification link!"
    echo "You must verify the email before you can send emails."
else
    echo "Note: Email may already be verified or verification in progress"
fi

echo ""
echo "Waiting for verification..."
echo "(This may take a few minutes after you click the verification link)"
echo ""

# Wait for verification (with timeout)
MAX_WAIT=300  # 5 minutes
WAITED=0
VERIFIED=false

while [ $WAITED -lt $MAX_WAIT ]; do
    STATUS=$(aws ses get-identity-verification-attributes \
        --identities "$SENDER_EMAIL" \
        --query "VerificationAttributes.\"$SENDER_EMAIL\".VerificationStatus" \
        --output text 2>/dev/null || echo "Pending")

    if [ "$STATUS" = "Success" ]; then
        echo "✓ Email verified successfully!"
        VERIFIED=true
        break
    elif [ "$STATUS" = "Failed" ]; then
        echo "✗ Verification failed. Please try again."
        exit 1
    fi

    # Show progress
    echo -n "."
    sleep 10
    WAITED=$((WAITED + 10))
done

echo ""

if [ "$VERIFIED" = false ]; then
    echo "⚠ Verification still pending. Continue anyway? (y/n)"
    read -p "> " CONTINUE
    if [ "$CONTINUE" != "y" ] && [ "$CONTINUE" != "Y" ]; then
        echo "Setup cancelled. Run this script again after email verification."
        exit 0
    fi
fi

# Check if terraform.tfvars exists
TFVARS_FILE="$PROJECT_ROOT/terraform/terraform.tfvars"

echo ""
echo "Step 2: Configuring Terraform variables..."
echo ""

if [ -f "$TFVARS_FILE" ]; then
    echo "terraform.tfvars already exists"
    read -p "Overwrite sender_email? (y/n): " OVERWRITE

    if [ "$OVERWRITE" = "y" ] || [ "$OVERWRITE" = "Y" ]; then
        # Update or add sender_email
        if grep -q "sender_email" "$TFVARS_FILE"; then
            # Update existing
            sed -i.bak "s|sender_email.*|sender_email = \"$SENDER_EMAIL\"|" "$TFVARS_FILE"
            echo "✓ Updated sender_email in terraform.tfvars"
        else
            # Add new
            echo "" >> "$TFVARS_FILE"
            echo "# SES Configuration" >> "$TFVARS_FILE"
            echo "sender_email = \"$SENDER_EMAIL\"" >> "$TFVARS_FILE"
            echo "sender_name = \"InsureMail AI Support\"" >> "$TFVARS_FILE"
            echo "✓ Added sender_email to terraform.tfvars"
        fi
    fi
else
    # Create new tfvars file
    cat > "$TFVARS_FILE" <<EOF
# InsureMail AI Terraform Variables

project_name = "insuremail-ai"
environment  = "dev"
aws_region   = "us-east-1"

# SES Configuration
sender_email = "$SENDER_EMAIL"
sender_name  = "InsureMail AI Support"

# Optional: Specify which emails to receive (empty = all)
ses_receipt_recipients = []
EOF
    echo "✓ Created terraform.tfvars with sender_email"
fi

# Show SES status
echo ""
echo "Step 3: Checking SES status..."
echo ""

# Get send quota
QUOTA=$(aws ses get-send-quota --output json)
MAX_24=$(echo "$QUOTA" | grep -o '"Max24HourSend":[0-9.]*' | cut -d: -f2)
SENT_24=$(echo "$QUOTA" | grep -o '"SentLast24Hours":[0-9.]*' | cut -d: -f2)

echo "SES Sending Limits:"
echo "  - Max per 24 hours: $MAX_24"
echo "  - Sent in last 24 hours: $SENT_24"
echo ""

if [ $(echo "$MAX_24 < 1000" | bc) -eq 1 ]; then
    echo "⚠ WARNING: SES is in SANDBOX mode"
    echo ""
    echo "Sandbox limitations:"
    echo "  - Can only send to verified email addresses"
    echo "  - Limited to 200 emails per 24 hours"
    echo "  - 1 email per second"
    echo ""
    echo "To request production access:"
    echo "  1. Go to AWS Console → SES → Account Dashboard"
    echo "  2. Click 'Request production access'"
    echo "  3. Fill out the form (typically approved within 24 hours)"
    echo ""
fi

# Next steps
echo ""
echo "========================================="
echo "✓ SES Setup Complete!"
echo "========================================="
echo ""
echo "Sender email: $SENDER_EMAIL"
echo ""
echo "Next Steps:"
echo ""
echo "1. Deploy infrastructure:"
echo "   cd $PROJECT_ROOT/terraform"
echo "   terraform apply"
echo ""
echo "2. (For receiving emails) Add MX record to your DNS:"
echo "   Name: yourdomain.com"
echo "   Type: MX"
echo "   Priority: 10"
echo "   Value: inbound-smtp.us-east-1.amazonaws.com"
echo ""
echo "3. Test the system:"
echo "   - Send test email to: $SENDER_EMAIL"
echo "   - Check CloudWatch Logs for processing"
echo "   - Verify auto-response is sent"
echo ""
echo "4. (Optional) Request production access to remove sandbox limits"
echo ""
echo "Full documentation: docs/SES_SETUP.md"
echo ""
