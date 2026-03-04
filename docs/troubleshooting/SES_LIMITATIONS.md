# Amazon SES Email Receiving Limitations

Understanding SES receiving architecture and workarounds for testing.

---

## The Problem

**Scenario**: You send an email from `gmail-user-a@gmail.com` to `gmail-user-b@gmail.com`, expecting SES to intercept and process it. But nothing happens - no S3 upload, no Step Functions execution, no response.

**Why**: Gmail delivers the email directly within its own infrastructure. Amazon SES never sees the email.

---

## How SES Email Receiving Works

### The Architecture

```
Sender → Internet → MX Records → SES Receipt Rules → S3/SNS/Lambda
```

**Key Point**: SES can only receive emails sent **TO** domains/addresses that have MX records pointing to SES.

### What SES Can Do

✅ **Works**: Receive emails sent TO addresses on domains you control
  - Example: someone@gmail.com → support@yourdomain.com (if yourdomain.com MX → SES)

✅ **Works**: Receive emails FROM any sender
  - Example: anyone@anywhere.com → your-ses-address@yourdomain.com

### What SES Cannot Do

❌ **Doesn't Work**: Intercept emails between third-party domains
  - Example: gmail-a@gmail.com → gmail-b@gmail.com
  - Gmail's servers handle this internally, SES never sees it

❌ **Doesn't Work**: Receive emails TO addresses without proper MX records
  - Example: anything@gmail.com (Gmail owns the MX records, not you)

---

## Why Gmail-to-Gmail Fails

When you send email from `yilinglei907@gmail.com` to `shiyizhiya@gmail.com`:

1. Gmail's SMTP server receives the email from sender
2. Gmail looks up MX records for `@gmail.com` domain
3. Gmail finds its own MX servers
4. Gmail delivers directly to recipient's Gmail inbox
5. **SES is never involved in this transaction**

---

## Solutions for Testing

### Solution 1: Use the Simulation Script ⭐ **RECOMMENDED**

Bypasses SES entirely and directly triggers the workflow:

```bash
bash scripts/simulate_email_workflow.sh
```

**What it does:**
1. Creates email file locally
2. Uploads directly to S3 bucket
3. Triggers Step Functions with proper SNS message format
4. Monitors execution
5. Displays results

**Pros:**
- ✅ Works in any environment
- ✅ No domain setup required
- ✅ Full control over test data
- ✅ Perfect for development/testing

**Cons:**
- ❌ Doesn't test actual SES receiving
- ❌ Manual process

### Solution 2: Set Up Custom Domain

Configure a custom domain with SES MX records:

#### Step 1: Get a Domain

```bash
# Option A: Use existing domain
# Option B: Register new domain via Route 53
aws route53domains register-domain --domain-name yourdomain.com ...
```

#### Step 2: Verify Domain in SES

```bash
aws ses verify-domain-identity --domain yourdomain.com
```

#### Step 3: Add MX Records

Add these MX records to your domain's DNS:

```
Priority 10: inbound-smtp.us-east-1.amazonaws.com
```

For Route 53:

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR-ZONE-ID \
  --change-batch file://mx-records.json
```

`mx-records.json`:
```json
{
  "Changes": [{
    "Action": "CREATE",
    "ResourceRecordSet": {
      "Name": "yourdomain.com",
      "Type": "MX",
      "TTL": 300,
      "ResourceRecords": [
        {"Value": "10 inbound-smtp.us-east-1.amazonaws.com"}
      ]
    }
  }]
}
```

#### Step 4: Update SES Receipt Rule

```bash
# Update recipient to your custom domain
aws ses update-receipt-rule \
  --rule-set-name default-rule-set \
  --rule '{
    "Name": "insuremail-ai-dev-receipt-rule",
    "Recipients": ["support@yourdomain.com", "*@yourdomain.com"],
    ...
  }'
```

#### Step 5: Test

```bash
# Now this will work:
echo "Test" | mail -s "Subject" support@yourdomain.com
```

**Pros:**
- ✅ Tests actual SES receiving
- ✅ Production-like setup
- ✅ Can handle any sender

**Cons:**
- ❌ Requires domain ownership
- ❌ DNS propagation wait time
- ❌ Additional cost for domain (~$12/year)

### Solution 3: Use SES with Verified Addresses (Limited)

Use SES to send TO verified addresses, but this doesn't test receiving:

```bash
# Verify recipient address
aws ses verify-email-identity --email-address recipient@example.com

# Send test email via SES
aws ses send-email \
  --from sender@verified-domain.com \
  --to recipient@example.com \
  --subject "Test" \
  --text "Body"
```

**Pros:**
- ✅ Tests SES sending
- ✅ No domain required

**Cons:**
- ❌ Doesn't test SES receiving
- ❌ Requires email verification
- ❌ Only tests half the workflow

---

## Understanding SES Sandbox Mode

### What is Sandbox Mode?

New AWS accounts start in SES "sandbox mode" with these restrictions:

**Sending Limitations:**
- ❌ Can only send TO verified email addresses
- ❌ Can only send FROM verified email addresses/domains
- ✅ Can send up to 200 emails per day
- ✅ 1 email per second rate limit

**Receiving Limitations:**
- ✅ Can receive emails from ANY sender
- ✅ No receiving restrictions (only MX record requirement)

### How to Exit Sandbox Mode

Request production access:

```bash
./scripts/request_production_access.sh
```

Or manually via AWS Console:
1. Go to SES Console → Account Dashboard
2. Click "Request production access"
3. Fill out form:
   - Use case: "Email automation for insurance customer support"
   - Expected volume: Your estimate
   - Bounce/complaint handling: Describe your process
4. Submit request

**Timeline**: Typically approved within 24-48 hours

**After Approval:**
- ✅ Can send to ANY email address (no verification)
- ✅ Sending limit increases to 50,000 emails/day
- ✅ Rate limit increases to 14 emails/second
- ✅ No change to receiving (already unrestricted)

---

## Current Receipt Rule Configuration

Your SES receipt rule is configured as:

```bash
aws ses describe-receipt-rule \
  --rule-set-name default-rule-set \
  --rule-name insuremail-ai-dev-receipt-rule
```

**Current Recipients:**
```json
{
  "Recipients": ["shiyizhiya@gmail.com"]
}
```

**Why This Doesn't Work:**
- Gmail owns `@gmail.com` domain
- Gmail's MX records point to Gmail servers, not SES
- SES never sees emails sent to `@gmail.com` addresses

**To Fix**: Update to your custom domain:
```json
{
  "Recipients": ["support@yourdomain.com", "*@yourdomain.com"]
}
```

---

## Recommended Workflow

### For Development/Testing (Current)

Use the simulation script:

```bash
# Test complete workflow
bash scripts/simulate_email_workflow.sh

# Enter test data when prompted
From: test-sender@example.com
To: test-recipient@example.com
Subject: Claim inquiry
Body: I need help with policy #12345
```

### For Production

Set up custom domain:

1. Register domain (e.g., `insuremail-ai.com`)
2. Configure MX records to point to SES
3. Update SES receipt rule for `*@insuremail-ai.com`
4. Configure sender domain (SPF, DKIM, DMARC)
5. Request SES production access
6. Test with real emails

---

## Diagram: Email Receiving Flow

### Gmail to Gmail (Doesn't Work)

```
[Sender Gmail] → Gmail SMTP → Gmail MX → [Recipient Gmail]
                                ↑
                          (SES never sees this)
```

### Custom Domain (Works)

```
[Any Sender] → Internet → Your Domain MX Records
                                ↓
                          Amazon SES
                                ↓
                          Receipt Rules
                                ↓
                          S3 + SNS + Lambda
                                ↓
                          Step Functions
```

---

## FAQ

### Q: Can I use AWS WorkMail instead?

**A**: Yes, WorkMail provides mailboxes with MX records automatically. But it costs $4/user/month.

### Q: Can I use a free subdomain?

**A**: Some DNS providers (Cloudflare, etc.) offer free subdomains. You can configure MX records for these.

### Q: Does this affect email sending?

**A**: No, SES sending works independently. You can still send emails even in sandbox mode (to verified addresses).

### Q: What about email forwarding services?

**A**: Services like ForwardEmail can forward emails to your SES-configured domain, but this adds complexity.

---

## Summary

**The Core Issue**: You cannot use Gmail-to-Gmail (or any third-party-to-third-party domain) for testing SES email receiving because SES requires MX record control.

**Best Solution for Testing**: Use `scripts/simulate_email_workflow.sh`

**Best Solution for Production**: Set up custom domain with SES MX records

**Timeline**:
- Simulation script: ✅ **Works immediately**
- Custom domain setup: ⏱️ **1-2 hours (+ DNS propagation)**
- SES production access: ⏱️ **24-48 hours (for sending limits)**

---

**See Also**:
- [SES_SETUP.md](../guides/SES_SETUP.md) - Complete SES configuration
- [EMAIL_INTEGRATION.md](../guides/EMAIL_INTEGRATION.md) - Email integration details
- [scripts/simulate_email_workflow.sh](../../scripts/simulate_email_workflow.sh) - Testing script
