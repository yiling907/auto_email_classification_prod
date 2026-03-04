# Amazon SES Setup Guide

This guide explains how to configure Amazon SES for real email integration with InsureMail AI.

## Overview

The system uses Amazon SES for:
- **Receiving emails**: SES → S3 → SNS → Lambda → Step Functions
- **Sending emails**: Lambda → SES → Recipient

## Prerequisites

- AWS Account with SES service available
- Verified email address or domain
- SES sandbox mode removal (for production)

---

## Step 1: Verify Sender Email Address

Before you can send emails, you must verify your sender email in SES.

### Option A: Verify Individual Email (Development)

```bash
# Set your sender email
SENDER_EMAIL="support@yourdomain.com"

# Request verification
aws ses verify-email-identity --email-address $SENDER_EMAIL

# Check your email inbox for verification link from AWS
# Click the link to complete verification
```

### Option B: Verify Domain (Production Recommended)

```bash
# Verify your domain
DOMAIN="yourdomain.com"

aws ses verify-domain-identity --domain $DOMAIN

# This will return verification token - add this as a TXT record in your DNS
```

Add DNS TXT record:
```
Name: _amazonses.yourdomain.com
Type: TXT
Value: <verification-token-from-above>
```

---

## Step 2: Configure Terraform Variables

Update `terraform.tfvars`:

```hcl
# Your verified sender email
sender_email = "support@yourdomain.com"

# Display name for emails
sender_name = "InsureMail AI Support"

# Email addresses to receive emails (leave empty for all)
ses_receipt_recipients = []  # Empty = receive all emails to this domain
# OR specify specific addresses:
# ses_receipt_recipients = ["support@yourdomain.com", "claims@yourdomain.com"]
```

---

## Step 3: Deploy Infrastructure

```bash
cd terraform

# Initialize Terraform (if needed)
terraform init

# Plan to see what will be created
terraform plan

# Apply changes
terraform apply
```

This will create:
- SNS topic for SES notifications
- SES receipt rule set
- S3 bucket policy for SES
- Lambda triggers

---

## Step 4: Configure MX Records (For Receiving Emails)

To receive emails, add MX records to your domain's DNS:

```bash
# Get the MX record value for your region
# For us-east-1:
MX_RECORD="10 inbound-smtp.us-east-1.amazonaws.com"
```

Add DNS MX record:
```
Name: yourdomain.com  (or subdomain like mail.yourdomain.com)
Type: MX
Priority: 10
Value: inbound-smtp.us-east-1.amazonaws.com
```

**Regional endpoints:**
- us-east-1: `inbound-smtp.us-east-1.amazonaws.com`
- us-west-2: `inbound-smtp.us-west-2.amazonaws.com`
- eu-west-1: `inbound-smtp.eu-west-1.amazonaws.com`
- See full list: https://docs.aws.amazon.com/ses/latest/dg/regions.html

---

## Step 5: Check SES Status

```bash
# Check email verification status
aws ses get-identity-verification-attributes --identities $SENDER_EMAIL

# Check SES sending limits
aws ses get-send-quota

# Check SES receipt rule sets
aws ses describe-active-receipt-rule-set
```

---

## Step 6: Request Production Access (Remove Sandbox)

**SES Sandbox Limitations:**
- Can only send to verified email addresses
- Limited to 200 emails per 24 hours
- 1 email per second

**To request production access:**

1. Go to AWS Console → SES → Account Dashboard
2. Click "Request production access"
3. Fill out the form:
   - **Use case**: Customer support automation for insurance company
   - **Website URL**: Your company website
   - **How will you handle bounces/complaints**: Describe your process
   - **Opt-out process**: Describe unsubscribe mechanism
   - **Expected volume**: Estimate emails per day

4. AWS typically responds within 24 hours

---

## Architecture Flow

### Receiving Emails

```
Email Sent to support@yourdomain.com
          ↓
    Amazon SES (via MX record)
          ↓
    Store in S3 (bucket/incoming/)
          ↓
    Publish to SNS Topic
          ↓
    Trigger Lambda (email_receiver)
          ↓
    Start Step Functions Workflow
          ↓
    Process Email (Parse → Classify → Generate Response)
          ↓
    Send Response (email_sender Lambda)
```

### Sending Emails

```
Step Functions → Email Sender Lambda
          ↓
    Amazon SES (SendEmail API)
          ↓
    Recipient's email inbox
```

---

## Testing

### Test Receiving

1. Send a test email to your configured address:
   ```bash
   echo "Test email body" | mail -s "Test Subject" support@yourdomain.com
   ```

2. Check CloudWatch Logs:
   ```bash
   # Email receiver Lambda logs
   aws logs tail /aws/lambda/insuremail-ai-dev-email-receiver --follow

   # Step Functions execution
   aws stepfunctions list-executions \
     --state-machine-arn $(terraform output -raw state_machine_arn) \
     --max-results 5
   ```

3. Check S3 bucket:
   ```bash
   # List received emails
   aws s3 ls s3://$(terraform output -raw email_bucket_name)/incoming/
   ```

### Test Sending

```bash
# Invoke email sender Lambda directly
aws lambda invoke \
  --function-name insuremail-ai-dev-email-sender \
  --payload '{
    "email_id": "test-123",
    "recipient_email": "your-verified-email@example.com",
    "subject": "Test Inquiry",
    "response_text": "Thank you for contacting us. This is a test response.",
    "confidence_score": 0.85
  }' \
  response.json

cat response.json
```

---

## Monitoring

### CloudWatch Metrics

```bash
# SES sending metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/SES \
  --metric-name Send \
  --statistics Sum \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600

# Lambda invocations
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=insuremail-ai-dev-email-sender \
  --statistics Sum \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600
```

### SES Reputation Monitoring

```bash
# Check bounce and complaint rates
aws ses get-account-sending-enabled

# View SES sending statistics
aws ses get-send-statistics
```

---

## Troubleshooting

### Issue: "Email address is not verified"

**Solution:**
```bash
# Verify the sender email
aws ses verify-email-identity --email-address support@yourdomain.com

# Check verification status
aws ses get-identity-verification-attributes --identities support@yourdomain.com
```

### Issue: "MessageRejected: Email address is not verified"

**Cause**: SES is in sandbox mode and recipient is not verified

**Solution:**
1. Verify recipient email for testing:
   ```bash
   aws ses verify-email-identity --email-address test@example.com
   ```
2. OR request production access (see Step 6)

### Issue: "Not receiving emails"

**Checklist:**
1. MX records configured correctly?
   ```bash
   dig MX yourdomain.com
   ```
2. SES receipt rule active?
   ```bash
   aws ses describe-active-receipt-rule-set
   ```
3. S3 bucket policy allows SES?
   ```bash
   aws s3api get-bucket-policy --bucket your-bucket-name
   ```
4. Check CloudWatch Logs for errors

### Issue: "Email sent but not triggering workflow"

**Cause**: SNS → Lambda trigger not configured

**Solution:**
```bash
# Check SNS subscriptions
aws sns list-subscriptions-by-topic \
  --topic-arn $(terraform output -raw ses_sns_topic_arn)

# Check Lambda permissions
aws lambda get-policy \
  --function-name insuremail-ai-dev-email-receiver
```

---

## Cost Estimation

### SES Pricing (US East 1)

**Receiving emails:**
- First 1,000 emails/month: **FREE**
- After: $0.10 per 1,000 emails

**Sending emails:**
- First 62,000 emails/month (from EC2): **FREE**
- After: $0.10 per 1,000 emails
- From Lambda: $0.10 per 1,000 emails (no free tier)

**Data transfer:**
- Attachments stored in S3: Standard S3 pricing

### Monthly Cost Examples

**Low volume (100 emails/day):**
- Receiving: 3,000 emails/month = FREE
- Sending: 2,000 emails/month = $0.20
- **Total: ~$0.20/month**

**Medium volume (1,000 emails/day):**
- Receiving: 30,000 emails/month = $2.90
- Sending: 20,000 emails/month = $2.00
- **Total: ~$5/month**

**High volume (10,000 emails/day):**
- Receiving: 300,000 emails/month = $29.90
- Sending: 200,000 emails/month = $20.00
- **Total: ~$50/month**

---

## Security Best Practices

### 1. Use Domain Verification (Not Individual Emails)

Domain verification is more secure and allows sending from any address @yourdomain.com

### 2. Implement DKIM

Add DKIM signing for better deliverability:

```bash
aws ses set-identity-dkim-enabled \
  --identity yourdomain.com \
  --dkim-enabled
```

### 3. Configure SPF Record

Add SPF record to DNS:
```
v=spf1 include:amazonses.com ~all
```

### 4. Monitor Bounce and Complaint Rates

- Keep bounce rate < 5%
- Keep complaint rate < 0.1%
- Set up SNS notifications for bounces

### 5. Implement Email Feedback Loop

```bash
# Configure bounce/complaint notifications
aws ses set-identity-notification-topic \
  --identity yourdomain.com \
  --notification-type Bounce \
  --sns-topic arn:aws:sns:us-east-1:ACCOUNT:ses-bounces
```

---

## Next Steps

After SES is configured:

1. **Test end-to-end flow**: Send test email and verify response
2. **Configure monitoring**: Set up CloudWatch alarms for failures
3. **Request production access**: Remove sandbox limitations
4. **Add DKIM/SPF**: Improve email deliverability
5. **Implement feedback loop**: Handle bounces and complaints

---

## Summary

**Quick Setup Checklist:**
- [ ] Verify sender email in SES
- [ ] Update terraform.tfvars with sender email
- [ ] Run `terraform apply`
- [ ] Add MX records to DNS (for receiving)
- [ ] Test sending and receiving
- [ ] Request production access
- [ ] Configure SPF/DKIM records

For questions or issues, check CloudWatch Logs:
```bash
# Email receiver logs
aws logs tail /aws/lambda/insuremail-ai-dev-email-receiver --follow

# Email sender logs
aws logs tail /aws/lambda/insuremail-ai-dev-email-sender --follow

# Step Functions logs
aws logs tail /aws/vendedlogs/states/insuremail-ai-dev-email-processing --follow
```
