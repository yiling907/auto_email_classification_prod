# Gmail IMAP Setup Guide

Complete guide for setting up Gmail IMAP polling for email receiving (replaces SES receiving).

---

## Overview

**Architecture Change**: InsureMail AI now uses **Gmail IMAP polling** instead of SES receiving.

### Why IMAP Instead of SES Receiving?

- ✅ **Works with existing Gmail accounts** - No custom domain needed
- ✅ **Simple setup** - Just need Gmail App Password
- ✅ **Cost-effective** - No additional AWS charges
- ✅ **Immediate testing** - No MX record configuration required

**Trade-offs:**
- ⏱️ Polling interval: 5 minutes (vs instant with SES)
- 📊 Cost: ~$0.002/month for Lambda polling (minimal)

---

## Prerequisites

1. **Gmail Account**
2. **2-Step Verification Enabled**
3. **IMAP Access Enabled**

---

## Quick Setup

### Option 1: Automated Setup Script (Recommended)

```bash
cd scripts
./setup_gmail_imap.sh
```

This script will:
1. Check 2-Step Verification
2. Guide you to generate App Password
3. Test IMAP connection
4. Save credentials to terraform.tfvars

### Option 2: Manual Setup

#### Step 1: Enable 2-Step Verification

1. Go to https://myaccount.google.com/security
2. Find "2-Step Verification" section
3. If "Off", click and enable it
4. Follow the setup instructions

#### Step 2: Generate App Password

1. Go to https://myaccount.google.com/apppasswords
2. Sign in if prompted
3. Select app: **Mail**
4. Select device: **Other (Custom name)**
5. Enter name: **InsureMail AI IMAP**
6. Click **Generate**
7. **Copy the 16-character password** (format: `xxxx xxxx xxxx xxxx`)

**IMPORTANT**: Save this password - you won't see it again!

#### Step 3: Enable IMAP in Gmail

1. Open Gmail
2. Click Settings (gear icon) → **See all settings**
3. Go to **Forwarding and POP/IMAP** tab
4. Under "IMAP access", select **Enable IMAP**
5. Click **Save Changes**

#### Step 4: Configure Terraform

Create `terraform/terraform.tfvars`:

```hcl
# Gmail IMAP Configuration
gmail_address      = "your-email@gmail.com"
gmail_app_password = "abcd efgh ijkl mnop"  # Your 16-character App Password
imap_server        = "imap.gmail.com"
mark_emails_as_read = true
imap_poll_interval_minutes = 5

# SES Configuration (for sending responses)
sender_email = "your-verified-email@gmail.com"
sender_name  = "InsureMail AI Support"
```

**Security Note**: Add `terraform.tfvars` to `.gitignore` (already done)

#### Step 5: Deploy

```bash
cd terraform
terraform init
terraform apply
```

---

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Gmail Inbox                                             │
│  (New unread emails)                                     │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ Polls every 5 minutes
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Gmail IMAP Poller Lambda                               │
│  - Connects via IMAP                                    │
│  - Fetches unread emails                                │
│  - Uploads to S3                                        │
│  - Triggers Step Functions                              │
│  - Marks as read (optional)                             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  S3 Bucket (insuremail-ai-dev-emails)                   │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Step Functions Workflow                                │
│  (Same as before - no changes)                          │
└─────────────────────────────────────────────────────────┘
```

### Polling Schedule

**EventBridge Rule**: Triggers Gmail IMAP poller every 5 minutes

```hcl
schedule_expression = "rate(5 minutes)"
```

**Adjust polling interval**:
```hcl
# In terraform.tfvars
imap_poll_interval_minutes = 3  # Poll every 3 minutes
```

**Note**: Gmail IMAP has rate limits (~450 requests/day), so avoid polling more than every 3 minutes.

---

## Testing

### Test IMAP Connection

```bash
# Using the setup script's test
python3 <<EOF
import imaplib

mail = imaplib.IMAP4_SSL('imap.gmail.com')
mail.login('your-email@gmail.com', 'your-app-password')
mail.select('inbox')

status, messages = mail.search(None, 'UNSEEN')
print(f"Unread emails: {len(messages[0].split())}")

mail.close()
mail.logout()
EOF
```

### Monitor Polling

```bash
# View Lambda logs
aws logs tail /aws/lambda/insuremail-ai-dev-gmail-imap-poller --follow

# Manually invoke poller
aws lambda invoke \
  --function-name insuremail-ai-dev-gmail-imap-poller \
  output.json && cat output.json | jq '.'
```

### Send Test Email

1. Send email TO your Gmail address (the one configured in `gmail_address`)
2. Wait up to 5 minutes for polling
3. Check CloudWatch logs
4. Verify Step Functions execution

```bash
# Check Step Functions executions
aws stepfunctions list-executions \
  --state-machine-arn $(cd terraform && terraform output -raw step_functions_arn) \
  --max-items 5
```

---

## Configuration Options

### Mark Emails as Read

**Default**: `true` (processed emails marked as read)

```hcl
# terraform.tfvars
mark_emails_as_read = false  # Keep emails unread after processing
```

### Polling Interval

**Default**: 5 minutes

```hcl
# terraform.tfvars
imap_poll_interval_minutes = 10  # Poll every 10 minutes (slower, cheaper)
```

### IMAP Server

**Default**: `imap.gmail.com`

For other email providers:

```hcl
# Outlook/Hotmail
imap_server = "imap-mail.outlook.com"

# Yahoo
imap_server = "imap.mail.yahoo.com"

# Custom IMAP server
imap_server = "imap.yourdomain.com"
```

---

## Troubleshooting

### Error: "IMAP authentication failed"

**Causes:**
1. Wrong App Password
2. 2-Step Verification not enabled
3. IMAP not enabled in Gmail

**Solutions:**
```bash
# 1. Verify 2-Step Verification is ON
open https://myaccount.google.com/security

# 2. Generate NEW App Password
open https://myaccount.google.com/apppasswords

# 3. Check IMAP is enabled
# Gmail → Settings → Forwarding and POP/IMAP → Enable IMAP

# 4. Test connection
python3 scripts/test_imap_connection.py
```

### Error: "No unread emails found"

**Not an error** - Just means no new emails. Send a test email to your Gmail address.

### Error: "Rate exceeded"

**Cause:** Polling too frequently

**Solution:** Increase polling interval:
```hcl
imap_poll_interval_minutes = 10  # Poll less frequently
```

Gmail IMAP limits: ~450 requests/day (~30 per hour = every 2 minutes max)

### Lambda Timeout

**Symptoms:** Lambda exceeds 120s timeout

**Solutions:**
1. Check internet connectivity from Lambda (add VPC NAT Gateway if in VPC)
2. Reduce batch size (process fewer emails per poll)
3. Increase timeout:

```hcl
# In terraform/modules/lambda/main.tf
timeout = 180  # Increase to 3 minutes
```

---

## Security Best Practices

### App Password Management

✅ **DO:**
- Use App Passwords (NOT regular Gmail password)
- Store in terraform.tfvars (add to .gitignore)
- Revoke unused App Passwords regularly
- Generate separate App Password for each application

❌ **DON'T:**
- Commit App Password to git
- Share App Password
- Use regular Gmail password

### Production Considerations

For production, use **AWS Secrets Manager**:

```hcl
# Store credentials in Secrets Manager
resource "aws_secretsmanager_secret" "gmail_credentials" {
  name = "insuremail-ai/gmail-imap"
}

resource "aws_secretsmanager_secret_version" "gmail_credentials" {
  secret_id = aws_secretsmanager_secret.gmail_credentials.id
  secret_string = jsonencode({
    gmail_address  = "your-email@gmail.com"
    gmail_app_password = "your-app-password"
  })
}

# Update Lambda to read from Secrets Manager
```

### Revoking App Password

If compromised, revoke immediately:

1. Go to https://myaccount.google.com/apppasswords
2. Find "InsureMail AI IMAP"
3. Click **Remove**
4. Generate new App Password
5. Update terraform.tfvars
6. Redeploy: `terraform apply`

---

## Cost Analysis

### Gmail IMAP Polling Cost

**Lambda Invocations:**
- 12 invocations/hour × 24 hours × 30 days = 8,640 invocations/month
- Free tier: 1M invocations/month
- **Cost: $0** (within free tier)

**Lambda Duration:**
- ~2 seconds per invocation (if no emails)
- ~10 seconds per invocation (with emails)
- Average: ~5 seconds
- 8,640 invocations × 5 seconds = 43,200 seconds = 12 hours
- At 256 MB memory: 12 GB-hours/month
- Free tier: 400,000 GB-seconds = 111 GB-hours
- **Cost: $0** (within free tier)

**Total Additional Cost: $0/month** (assuming within free tier)

### Comparison: IMAP vs SES Receiving

| Feature | Gmail IMAP | SES Receiving |
|---------|------------|---------------|
| Setup complexity | Easy | Complex (MX records) |
| Custom domain required | No | Yes ($12/year) |
| Polling delay | 5 minutes | Instant |
| Cost (monthly) | $0 | $0 (receiving is free) |
| **Best for** | **Testing, personal use** | **Production, instant processing** |

---

## Migration from SES

If you previously used SES receiving:

### What Changed

**Removed:**
- SNS topic for SES notifications
- SES receipt rules
- email_receiver Lambda function

**Added:**
- gmail_imap_poller Lambda function
- EventBridge rule for scheduled polling
- Gmail IMAP credentials in variables

**Unchanged:**
- SES email sending (for responses)
- All other Lambda functions
- Step Functions workflow
- DynamoDB tables
- S3 buckets

### Migration Steps

1. Run setup script: `./scripts/setup_gmail_imap.sh`
2. Deploy changes: `cd terraform && terraform apply`
3. Terraform will:
   - Remove SES receiving resources
   - Add Gmail IMAP poller
   - Add EventBridge polling schedule

**No data loss** - S3 buckets and DynamoDB tables unchanged.

---

## FAQ

### Can I use Outlook/Yahoo/other email providers?

**Yes!** Change the IMAP server:

```hcl
# Outlook
gmail_address = "your-email@outlook.com"
imap_server = "imap-mail.outlook.com"

# Yahoo
gmail_address = "your-email@yahoo.com"
imap_server = "imap.mail.yahoo.com"
```

Generate App Password following the provider's instructions.

### Will this work with G Suite/Google Workspace?

**Yes!** Same setup process. Your admin may need to:
1. Enable IMAP for your organization
2. Allow less secure apps (or use OAuth - more complex)

### Can I process multiple Gmail accounts?

**Not currently.** You'd need to:
1. Deploy separate Lambda functions for each account
2. Or modify the poller to handle multiple accounts

For production with multiple accounts, consider SES with custom domains instead.

### What happens to emails after processing?

**Default behavior** (`mark_emails_as_read = true`):
- Email remains in Gmail inbox
- Marked as "read"
- Original email unchanged

**Optional** (`mark_emails_as_read = false`):
- Email remains unread
- Will be reprocessed on next poll (creates duplicates!)

### How do I stop the poller?

**Option 1: Disable EventBridge rule:**
```bash
aws events disable-rule \
  --name insuremail-ai-dev-gmail-imap-poll
```

**Option 2: Delete Lambda:**
```bash
terraform destroy -target=module.lambda.aws_lambda_function.gmail_imap_poller
```

**Option 3: Destroy all infrastructure:**
```bash
terraform destroy
```

---

## Support

- **IMAP Connection Issues**: Check Gmail security settings
- **Lambda Errors**: Review CloudWatch logs
- **Polling Not Working**: Verify EventBridge rule is enabled

```bash
# Check EventBridge rule status
aws events describe-rule \
  --name insuremail-ai-dev-gmail-imap-poll

# View recent Lambda invocations
aws logs filter-log-events \
  --log-group-name /aws/lambda/insuremail-ai-dev-gmail-imap-poller \
  --start-time $(date -u -d '10 minutes ago' +%s)000
```

---

**Last Updated**: March 4, 2026
**Status**: Production-ready ✅
