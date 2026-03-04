#!/bin/bash

# Setup script for Gmail IMAP configuration
# Helps users generate App Password and configure Gmail for IMAP polling

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Gmail IMAP Setup for InsureMail AI${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

echo -e "${YELLOW}Prerequisites:${NC}"
echo "  1. Gmail account"
echo "  2. 2-Step Verification enabled on Gmail"
echo "  3. Access to Google Account settings"
echo

# Step 1: Check if 2FA is enabled
echo -e "${BLUE}Step 1: Enable 2-Step Verification${NC}"
echo
echo -e "${YELLOW}You MUST have 2-Step Verification enabled to create App Passwords.${NC}"
echo
echo "To check/enable 2-Step Verification:"
echo "  1. Go to: https://myaccount.google.com/security"
echo "  2. Look for '2-Step Verification' section"
echo "  3. If it says 'Off', click and follow setup instructions"
echo "  4. If it says 'On', you're good to proceed!"
echo

read -p "Is 2-Step Verification enabled on your Gmail? (y/n): " TWO_FA_ENABLED

if [ "$TWO_FA_ENABLED" != "y" ] && [ "$TWO_FA_ENABLED" != "Y" ]; then
    echo -e "${RED}✗ Please enable 2-Step Verification first and run this script again.${NC}"
    echo "   Visit: https://myaccount.google.com/security"
    exit 1
fi

# Step 2: Generate App Password
echo
echo -e "${BLUE}Step 2: Generate Gmail App Password${NC}"
echo
echo -e "${YELLOW}App Passwords are 16-character codes that allow apps to access your Gmail.${NC}"
echo -e "${YELLOW}This is NOT your regular Gmail password - it's specifically for this app.${NC}"
echo
echo "To generate an App Password:"
echo "  1. Go to: https://myaccount.google.com/apppasswords"
echo "  2. You may need to sign in again"
echo "  3. Select 'Mail' as the app"
echo "  4. Select 'Other (Custom name)' as the device"
echo "  5. Enter name: 'InsureMail AI IMAP'"
echo "  6. Click 'Generate'"
echo "  7. Copy the 16-character password (format: xxxx xxxx xxxx xxxx)"
echo
echo -e "${RED}IMPORTANT: Save this password - you won't be able to see it again!${NC}"
echo

read -p "Press Enter when you've generated the App Password..."

# Step 3: Collect credentials
echo
echo -e "${BLUE}Step 3: Enter Your Gmail Credentials${NC}"
echo

read -p "Enter your Gmail address (e.g., your-email@gmail.com): " GMAIL_ADDRESS

if [[ ! "$GMAIL_ADDRESS" =~ ^[A-Za-z0-9._%+-]+@gmail\.com$ ]]; then
    echo -e "${RED}✗ Invalid Gmail address format${NC}"
    exit 1
fi

echo
echo "Enter your App Password (16 characters, spaces optional):"
echo -e "${YELLOW}Note: This is the 16-character code from Step 2, NOT your Gmail password${NC}"
read -s -p "App Password: " APP_PASSWORD
echo

# Remove spaces from app password
APP_PASSWORD=$(echo "$APP_PASSWORD" | tr -d ' ')

# Validate app password length
if [ ${#APP_PASSWORD} -ne 16 ]; then
    echo -e "${RED}✗ App Password must be exactly 16 characters (excluding spaces)${NC}"
    echo "   You entered: ${#APP_PASSWORD} characters"
    exit 1
fi

# Step 4: Test IMAP connection
echo
echo -e "${BLUE}Step 4: Test IMAP Connection${NC}"
echo

echo "Testing connection to Gmail IMAP..."

# Create Python test script
cat > /tmp/test_imap.py <<EOF
import imaplib
import sys

try:
    # Connect to Gmail IMAP
    mail = imaplib.IMAP4_SSL('imap.gmail.com')

    # Login
    mail.login('${GMAIL_ADDRESS}', '${APP_PASSWORD}')

    # Select inbox
    mail.select('inbox')

    # Count emails
    status, messages = mail.search(None, 'ALL')
    email_count = len(messages[0].split())

    # Close connection
    mail.close()
    mail.logout()

    print(f"✓ Connection successful!")
    print(f"✓ Found {email_count} emails in inbox")
    sys.exit(0)

except imaplib.IMAP4.error as e:
    print(f"✗ IMAP authentication failed: {e}")
    print("\nPossible issues:")
    print("  1. Wrong App Password")
    print("  2. 2-Step Verification not enabled")
    print("  3. IMAP not enabled in Gmail settings")
    sys.exit(1)

except Exception as e:
    print(f"✗ Connection error: {e}")
    sys.exit(1)
EOF

python3 /tmp/test_imap.py
TEST_RESULT=$?

rm /tmp/test_imap.py

if [ $TEST_RESULT -ne 0 ]; then
    echo
    echo -e "${RED}✗ IMAP connection test failed${NC}"
    echo
    echo "Troubleshooting:"
    echo "  1. Verify 2-Step Verification is ON: https://myaccount.google.com/security"
    echo "  2. Generate a NEW App Password: https://myaccount.google.com/apppasswords"
    echo "  3. Ensure IMAP is enabled in Gmail: Settings → See all settings → Forwarding and POP/IMAP"
    echo "  4. Try the setup script again"
    exit 1
fi

# Step 5: Save to terraform.tfvars
echo
echo -e "${BLUE}Step 5: Save Configuration${NC}"
echo

TFVARS_FILE="../terraform/terraform.tfvars"

if [ -f "$TFVARS_FILE" ]; then
    echo -e "${YELLOW}terraform.tfvars already exists. Backing up...${NC}"
    cp "$TFVARS_FILE" "${TFVARS_FILE}.backup.$(date +%s)"
fi

# Append Gmail configuration to tfvars
cat >> "$TFVARS_FILE" <<EOF

# Gmail IMAP Configuration (Added: $(date))
gmail_address      = "${GMAIL_ADDRESS}"
gmail_app_password = "${APP_PASSWORD}"
imap_server        = "imap.gmail.com"
mark_emails_as_read = true
EOF

echo -e "${GREEN}✓ Configuration saved to terraform/terraform.tfvars${NC}"

# Step 6: Summary
echo
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}   Setup Complete!${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo
echo "Configuration:"
echo "  Gmail Address: ${GMAIL_ADDRESS}"
echo "  App Password:  **************** (saved)"
echo "  IMAP Server:   imap.gmail.com"
echo "  Poll Interval: Every 5 minutes"
echo
echo "Next steps:"
echo "  1. Deploy infrastructure:"
echo "     cd terraform && terraform apply"
echo
echo "  2. The Gmail IMAP poller will:"
echo "     - Check your inbox every 5 minutes"
echo "     - Process unread emails"
echo "     - Mark them as read (configurable)"
echo "     - Trigger the AI workflow"
echo
echo "  3. Monitor polling:"
echo "     aws logs tail /aws/lambda/insuremail-ai-dev-gmail-imap-poller --follow"
echo
echo -e "${YELLOW}Security Notes:${NC}"
echo "  - App Password is stored in terraform.tfvars (add to .gitignore!)"
echo "  - Credentials are passed to Lambda as environment variables"
echo "  - Consider using AWS Secrets Manager for production"
echo "  - You can revoke App Password anytime at: https://myaccount.google.com/apppasswords"
echo
echo -e "${GREEN}✓ Gmail IMAP setup complete!${NC}"
