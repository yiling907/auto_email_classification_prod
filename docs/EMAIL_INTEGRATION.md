# Email Integration Guide

Complete guide for integrating InsureMail AI with real email systems.

## Overview

InsureMail AI now supports **bidirectional email integration**:
- **Receive emails**: Automatically process incoming emails via Amazon SES
- **Send responses**: Automatically reply with AI-generated responses

## Quick Start (5 Minutes)

### 1. Verify Your Email

```bash
./scripts/setup_ses.sh
```

This interactive script will:
- Prompt for your sender email address
- Verify it in Amazon SES
- Update terraform.tfvars automatically
- Show SES status and next steps

### 2. Deploy Infrastructure

```bash
cd terraform
terraform apply
```

### 3. Test the System

Send a test email to your configured address and check the dashboard for processing status.

---

## Detailed Setup

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Email Integration Flow                       │
└─────────────────────────────────────────────────────────────────┘

RECEIVING:
  Email → MX Record → Amazon SES → S3 (raw storage)
                          ↓
                      SNS Topic
                          ↓
                  Email Receiver Lambda
                          ↓
                  Step Functions Workflow
                          ↓
            Parse → Classify → RAG → CRM → Claude
                          ↓
                    Route by Confidence

SENDING:
  High Confidence (≥0.8) → Email Sender Lambda → Amazon SES → Recipient
  Medium (0.5-0.8)       → Queue for Review
  Low (<0.5)             → Escalate to Agent
```

### Components

#### 1. Email Receiver Lambda
- **Trigger**: SNS notification from SES
- **Function**: Parse SES message and start Step Functions execution
- **Input**: SES notification (JSON)
- **Output**: Execution ARN

#### 2. Email Sender Lambda
- **Trigger**: Step Functions (when confidence ≥ 0.8)
- **Function**: Send HTML email via SES
- **Input**: Email ID, recipient, response text, confidence score
- **Output**: SES message ID

#### 3. SES Configuration
- **Receipt Rule Set**: Route incoming emails to S3 + SNS
- **Email Identity**: Verified sender address
- **S3 Integration**: Store raw emails in incoming/ prefix
- **SNS Integration**: Notify Lambda of new emails

---

## Configuration Options

### Terraform Variables

```hcl
# Required: Your verified sender email
sender_email = "support@yourdomain.com"

# Optional: Display name
sender_name = "InsureMail AI Support"

# Optional: Filter incoming emails
ses_receipt_recipients = []  # Empty = all emails
# Or specific addresses:
ses_receipt_recipients = ["support@yourdomain.com", "claims@yourdomain.com"]
```

### Environment Variables (Lambda)

Automatically configured by Terraform:

**Email Receiver:**
- `STATE_MACHINE_ARN`: ARN of email processing workflow
- `EMAIL_BUCKET_NAME`: S3 bucket for storing emails

**Email Sender:**
- `EMAIL_TABLE_NAME`: DynamoDB table for email records
- `SENDER_EMAIL`: Verified sender address
- `SENDER_NAME`: Display name

---

## Email Features

### Receiving

**Supported formats:**
- Plain text emails
- HTML emails (converted to plain text)
- Multipart emails (extracts text/plain part)

**Metadata extracted:**
- From, To, Subject, Date
- Message ID
- Spam/virus/DKIM/SPF verdicts
- S3 storage location

**Security:**
- Email addresses redacted in logs (first 3 chars + domain)
- Spam and virus scanning enabled
- DKIM/SPF validation

### Sending

**Email template:**
- Professional HTML design
- Responsive layout
- Confidence score badge
- Company branding
- Auto-response disclaimer

**Features:**
- Both HTML and plain text versions
- Reply-to configured
- Subject line: "Re: {original subject}"
- Confidence score display
- Error handling with retries

---

## DNS Configuration

### For Receiving Emails

Add MX record to your domain:

```
Name:     yourdomain.com (or mail.yourdomain.com)
Type:     MX
Priority: 10
Value:    inbound-smtp.us-east-1.amazonaws.com
TTL:      300
```

**Regional MX records:**
- US East (N. Virginia): `inbound-smtp.us-east-1.amazonaws.com`
- US West (Oregon): `inbound-smtp.us-west-2.amazonaws.com`
- EU (Ireland): `inbound-smtp.eu-west-1.amazonaws.com`

### For Better Deliverability

#### SPF Record
```
Name:  yourdomain.com
Type:  TXT
Value: v=spf1 include:amazonses.com ~all
```

#### DKIM (Enable in SES)
```bash
aws ses set-identity-dkim-enabled \
  --identity yourdomain.com \
  --dkim-enabled
```

Then add the CNAME records provided by AWS to your DNS.

---

## Testing

### Test Receiving

#### 1. Send Test Email
```bash
# Using mail command
echo "I need help with my claim #12345" | \
  mail -s "Claim Status Inquiry" support@yourdomain.com

# Or use any email client
```

#### 2. Monitor Processing
```bash
# Email receiver logs
aws logs tail /aws/lambda/insuremail-ai-dev-email-receiver --follow

# Step Functions execution
aws stepfunctions list-executions \
  --state-machine-arn $(cd terraform && terraform output -raw state_machine_arn) \
  --max-results 5

# Check S3 for stored email
aws s3 ls s3://$(cd terraform && terraform output -raw email_bucket_name)/incoming/
```

#### 3. View in Dashboard
Open your dashboard URL and check:
- Recent emails section
- Email detail page
- Processing trace

### Test Sending

#### Direct Lambda Invocation
```bash
aws lambda invoke \
  --function-name insuremail-ai-dev-email-sender \
  --payload '{
    "email_id": "test-123",
    "recipient_email": "your@email.com",
    "subject": "Test Inquiry",
    "response_text": "Thank you for your inquiry. Our team will review your request and respond within 24 hours.",
    "confidence_score": 0.85
  }' \
  response.json

cat response.json
```

#### Via Step Functions
```bash
# Start execution with test data
cd terraform
terraform output -raw state_machine_arn | xargs -I {} \
  aws stepfunctions start-execution \
    --state-machine-arn {} \
    --name test-$(date +%s) \
    --input file://../tests/test_data/raw_emails/claim_inquiry.eml
```

---

## Monitoring & Alerts

### CloudWatch Metrics

**Email Receiving:**
- Lambda invocations (email_receiver)
- SNS message delivery success/failure
- Step Functions execution start count

**Email Sending:**
- SES send success/failure
- Lambda invocations (email_sender)
- Email delivery latency

### Recommended Alarms

```bash
# High error rate for email sender
aws cloudwatch put-metric-alarm \
  --alarm-name insuremail-email-sender-errors \
  --alarm-description "Email sender Lambda errors" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FunctionName,Value=insuremail-ai-dev-email-sender

# SES bounce rate
aws cloudwatch put-metric-alarm \
  --alarm-name insuremail-ses-bounce-rate \
  --metric-name Reputation.BounceRate \
  --namespace AWS/SES \
  --statistic Average \
  --period 3600 \
  --evaluation-periods 1 \
  --threshold 0.05 \
  --comparison-operator GreaterThanThreshold
```

---

## Production Checklist

### Before Going Live

- [ ] Verify sender email/domain in SES
- [ ] Request SES production access (remove sandbox)
- [ ] Configure DNS records (MX, SPF, DKIM)
- [ ] Test end-to-end email flow
- [ ] Set up CloudWatch alarms
- [ ] Configure bounce/complaint handling
- [ ] Test with various email clients
- [ ] Verify email deliverability (check spam folders)
- [ ] Set up monitoring dashboard
- [ ] Document escalation procedures

### SES Production Access

**Why it's needed:**
- Sandbox mode: Can only send to verified emails (max 200/day)
- Production: Can send to any email (50,000/day default)

**How to request:**
1. Go to AWS Console → SES → Account Dashboard
2. Click "Request production access"
3. Fill out the form:
   - Use case description
   - Website URL
   - Bounce/complaint handling
   - Opt-out process
4. Typically approved within 24 hours

---

## Cost Breakdown

### SES Costs (us-east-1)

**Receiving:**
- First 1,000 emails/month: FREE
- Additional: $0.10 per 1,000 emails

**Sending:**
- $0.10 per 1,000 emails (from Lambda)
- First 62,000 emails/month FREE (if sending from EC2)

**Example monthly costs:**
- 100 emails/day: ~$0.20/month
- 1,000 emails/day: ~$5/month
- 10,000 emails/day: ~$50/month

### Additional Costs
- S3 storage for emails: ~$0.023/GB
- Lambda invocations: Included in AWS free tier
- Step Functions executions: ~$0.025 per 1,000 transitions
- DynamoDB storage: Minimal (PAY_PER_REQUEST)

---

## Troubleshooting

### Common Issues

#### 1. Email not verified
```
Error: Email address is not verified
```

**Solution:**
```bash
aws ses verify-email-identity --email-address support@yourdomain.com
# Check your inbox for verification link
```

#### 2. Emails not being received
```
No emails appearing in S3 or triggering workflow
```

**Debug steps:**
1. Check MX record: `dig MX yourdomain.com`
2. Verify SES receipt rule: `aws ses describe-active-receipt-rule-set`
3. Check S3 bucket policy allows SES
4. Review CloudWatch Logs for SNS/Lambda

#### 3. Cannot send emails (sandbox mode)
```
MessageRejected: Email address is not verified
```

**Solution:**
- For testing: Verify recipient email
- For production: Request production access

#### 4. High bounce rate
```
SES account under review due to bounces
```

**Prevention:**
- Validate email addresses before sending
- Implement bounce handling
- Remove invalid addresses
- Monitor bounce metrics

### Debug Commands

```bash
# Check SES status
aws ses get-identity-verification-attributes \
  --identities support@yourdomain.com

# View send quota
aws ses get-send-quota

# Check receipt rules
aws ses describe-active-receipt-rule-set

# View recent email activity
aws ses get-send-statistics

# Test email delivery
aws ses send-email \
  --from support@yourdomain.com \
  --destination ToAddresses=test@example.com \
  --message "Subject={Data=Test},Body={Text={Data=Test email}}"
```

---

## Advanced Features

### Email Threading
Future enhancement to track conversation threads using In-Reply-To and References headers.

### Attachment Support
Future enhancement to process and store email attachments in S3.

### Custom Templates
Customize the email template in `lambda/email_sender/lambda_function.py`:

```python
def build_email_body(response_text: str, confidence_score: float) -> str:
    # Customize HTML template here
    return f"""
    <!DOCTYPE html>
    ...
    """
```

### Webhook Integration
Add webhook notifications when emails are processed:

```python
# In email_receiver Lambda
requests.post('https://your-webhook-url.com', json={
    'email_id': email_id,
    'status': 'processed',
    'confidence': confidence_score
})
```

---

## Best Practices

### Email Deliverability
1. Always use verified domain (not individual email)
2. Configure SPF, DKIM, and DMARC
3. Maintain bounce rate < 5%
4. Keep complaint rate < 0.1%
5. Use proper unsubscribe mechanisms

### Security
1. Never log full email addresses
2. Sanitize email content before processing
3. Implement rate limiting
4. Use SES spam/virus scanning
5. Validate sender domains

### Performance
1. Use batch operations for bulk emails
2. Implement exponential backoff for retries
3. Cache frequently accessed data
4. Monitor Lambda cold starts
5. Right-size Lambda memory

---

## Support

### Documentation
- Full SES setup: `docs/SES_SETUP.md`
- Roadmap: `docs/ROADMAP.md`
- Dashboard guide: `docs/DASHBOARD_GUIDE.md`

### Logs
```bash
# All Lambda functions
aws logs tail /aws/lambda/insuremail-ai-dev-email-receiver --follow
aws logs tail /aws/lambda/insuremail-ai-dev-email-sender --follow

# Step Functions
aws logs tail /aws/vendedlogs/states/insuremail-ai-dev-email-processing --follow
```

### Useful Commands
```bash
# Quick setup
./scripts/setup_ses.sh

# Deploy
cd terraform && terraform apply

# Test
./scripts/test_pipeline.sh

# View dashboard
cd dashboard/frontend && npm run dev
```
