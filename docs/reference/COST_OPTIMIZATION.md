# Cost Optimization Guide

Complete guide to minimizing costs while running InsureMail AI.

## Current Cost Profile (Optimized)

**Monthly cost for 1,000 emails/day: ~$15-20**

### Breakdown

| Service | Usage | Cost |
|---------|-------|------|
| **AWS Bedrock (Claude 3 Haiku)** | ~100K tokens/day | **$8-10/month** |
| **Amazon SES** | 30K emails/month | **$5/month** |
| **AWS Lambda** | ~60K invocations | **~$2/month** |
| **DynamoDB** | PAY_PER_REQUEST | **$2-3/month** |
| **S3 Storage** | ~5GB | **$0.12/month** |
| **Step Functions** | 30K executions | **$0.75/month** |
| **CloudWatch Logs** | 7-day retention | **$1/month** |
| **API Gateway** | Dashboard API | **$0.50/month** |
| **Total** | | **~$19/month** |

---

## Model Cost Optimization

### Current Setup (Cost-Optimized)

**Using Claude 3 Haiku for all tasks**
- Input: $0.25 per million tokens
- Output: $1.25 per million tokens
- Average email: ~500 input tokens, ~200 output tokens
- **Cost per email: ~$0.0004** (less than a penny per 25 emails)

### Cost Comparison

| Model | Input Cost | Output Cost | Cost per Email | vs Haiku |
|-------|-----------|-------------|----------------|----------|
| **Claude 3 Haiku** (Current) | $0.25/M | $1.25/M | $0.0004 | **Baseline** |
| Claude 3.5 Haiku | $1.00/M | $5.00/M | $0.0015 | 3.75x more |
| Claude 3 Sonnet | $3.00/M | $15.00/M | $0.0045 | **11.25x more** |
| Claude 3.5 Sonnet | $3.00/M | $15.00/M | $0.0045 | **11.25x more** |
| Claude 3 Opus | $15.00/M | $75.00/M | $0.0225 | **56x more** |

**Savings by using Haiku:**
- vs Sonnet: Save ~$120/month (for 30K emails)
- vs Opus: Save ~$660/month (for 30K emails)

---

## Cost Optimization Strategies

### 1. Use Claude 3 Haiku (Already Implemented ✅)

**What we did:**
- Changed from Sonnet to Haiku in `lambda/claude_response/lambda_function.py`
- Reduced model costs by **90%**
- Haiku is still highly capable for insurance emails

**Performance:**
- Haiku: 3-5 second response time
- Sonnet: 4-7 second response time
- Quality difference: Minimal for structured tasks

### 2. Optimize Token Usage

**Current implementation:**
```python
# Prompt is concise and focused
prompt = f"""You are an AI assistant for an insurance company.

Email: {email_body[:1000]}  # Truncate to 1000 chars
Intent: {intent}
Knowledge: {rag_documents[:3]}  # Top 3 only

Generate a response."""
```

**Recommendations:**
- ✅ Truncate long emails (implemented)
- ✅ Limit RAG context to top 3 docs (implemented)
- ✅ Use concise prompts (implemented)
- ⏳ Cache common prompts (future enhancement)

### 3. DynamoDB Cost Optimization (Already Implemented ✅)

**What we use:**
- PAY_PER_REQUEST billing mode
- No idle costs
- Pay only for actual reads/writes

**Cost:**
- Write: $1.25 per million requests
- Read: $0.25 per million requests
- For 30K emails: ~$2-3/month

**Alternative (NOT recommended for our use case):**
- Provisioned capacity: Fixed cost even if unused
- Better only for >100K emails/day

### 4. Lambda Memory Optimization

**Current configuration:**
```hcl
email_parser:     512 MB  (simple parsing)
claude_response:  1024 MB (Bedrock API calls)
rag_retrieval:    512 MB  (DynamoDB queries)
email_sender:     256 MB  (SES API)
```

**Cost formula:**
- $0.0000166667 per GB-second
- Lower memory = lower cost BUT may increase duration
- Our current settings are optimal

**Do NOT reduce memory below these values:**
- Bedrock calls: Need ≥1024MB for good performance
- Parsing: 512MB is minimum for large emails

### 5. S3 Cost Optimization (Already Implemented ✅)

**Current configuration:**
```hcl
# Lifecycle rule for old emails
lifecycle_rule {
  enabled = true
  transition {
    days          = 90
    storage_class = "GLACIER"
  }
  expiration {
    days = 365
  }
}
```

**Savings:**
- Standard storage: $0.023/GB/month
- Glacier: $0.004/GB/month (83% cheaper)
- Emails older than 90 days move to Glacier automatically

### 6. CloudWatch Logs Optimization (Already Implemented ✅)

**Current retention: 7 days**
- Good for debugging
- Automatic cleanup
- Cost: ~$1/month

**Cost by retention:**
- 1 day: $0.20/month
- 7 days: $1/month (current)
- 30 days: $3/month
- Never expire: $10+/month

**Keep at 7 days** - good balance of cost vs debugging capability

### 7. SES Cost Optimization

**Current costs:**
- Receiving: First 1,000 free, then $0.10/1,000
- Sending: $0.10/1,000 emails
- For 30K emails: ~$5/month

**Optimization tips:**
- ✅ Only send high-confidence responses (≥0.8)
- ✅ Use confidence thresholds to reduce volume
- ⏳ Batch notifications (future: daily digest instead of per-email)

**Don't send if:**
- Confidence < 0.8 (queue for review instead)
- Duplicate email detected
- Email marked as spam

---

## Cost Monitoring

### Set Up Billing Alerts

```bash
# Create SNS topic for alerts
aws sns create-topic --name insuremail-billing-alerts

# Subscribe your email
aws sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:ACCOUNT:insuremail-billing-alerts \
  --protocol email \
  --notification-endpoint your@email.com

# Create billing alarm (alert if cost > $25/month)
aws cloudwatch put-metric-alarm \
  --alarm-name insuremail-monthly-cost \
  --alarm-description "Alert if InsureMail AI costs exceed $25/month" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 21600 \
  --evaluation-periods 1 \
  --threshold 25 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=Currency,Value=USD
```

### Cost Explorer Tags

All resources are tagged for cost tracking:
```hcl
tags = {
  Project    = "InsureMail AI"
  Environment = "dev"
  ManagedBy  = "Terraform"
}
```

**View costs by project:**
1. Go to AWS Cost Explorer
2. Filter by tag: `Project = InsureMail AI`
3. Group by service

### Daily Cost Tracking

```bash
# Get current month costs
aws ce get-cost-and-usage \
  --time-period Start=$(date -u +%Y-%m-01),End=$(date -u +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=TAG,Key=Project

# Get costs by service
aws ce get-cost-and-usage \
  --time-period Start=$(date -u -d '7 days ago' +%Y-%m-%d),End=$(date -u +%Y-%m-%d) \
  --granularity DAILY \
  --metrics BlendedCost \
  --group-by Type=SERVICE
```

---

## Cost Scenarios

### Low Volume (100 emails/day)

| Service | Cost |
|---------|------|
| Bedrock (Haiku) | $0.80/month |
| SES | $0.20/month |
| Lambda | FREE (within free tier) |
| DynamoDB | $0.20/month |
| S3 | FREE (within free tier) |
| Step Functions | $0.08/month |
| CloudWatch | $0.50/month |
| **Total** | **~$2/month** |

### Medium Volume (1,000 emails/day) - Current Target

| Service | Cost |
|---------|------|
| Bedrock (Haiku) | $8/month |
| SES | $5/month |
| Lambda | $2/month |
| DynamoDB | $2/month |
| S3 | $0.12/month |
| Step Functions | $0.75/month |
| CloudWatch | $1/month |
| **Total** | **~$19/month** |

### High Volume (10,000 emails/day)

| Service | Cost |
|---------|------|
| Bedrock (Haiku) | $80/month |
| SES | $50/month |
| Lambda | $15/month |
| DynamoDB | $20/month |
| S3 | $1/month |
| Step Functions | $7.50/month |
| CloudWatch | $5/month |
| **Total** | **~$179/month** |

---

## Advanced Cost Optimization

### 1. Caching Responses (Future Enhancement)

**Concept:** Cache responses for similar emails

```python
# Check cache before calling Claude
cache_key = hashlib.md5(f"{intent}:{email_body[:500]}".encode()).hexdigest()
cached = cache_table.get_item(Key={'cache_key': cache_key})

if cached and cached['timestamp'] > (now - timedelta(days=7)):
    return cached['response']  # Save $0.0004
```

**Potential savings:**
- If 30% of emails are similar: Save $2.40/month
- Higher for FAQ-type inquiries

### 2. Batch Processing (Future Enhancement)

**Concept:** Process multiple emails in one Lambda invocation

```python
# Instead of 1 Lambda per email:
# Process 10 emails per Lambda invocation
# Reduce Lambda invocations by 90%
```

**Savings:**
- Lambda costs: Save $1.80/month

**Trade-off:**
- Slightly higher latency (batch every 5 minutes)
- More complex error handling

### 3. Reserved Capacity (NOT Recommended Yet)

**When to consider:**
- Predictable load >10,000 emails/day
- Can commit to 1-3 years
- Savings: 30-75%

**Current recommendation:**
- Stay with on-demand pricing
- More flexible for variable load

### 4. Spot Instances for Batch Jobs (N/A)

- Not applicable to Lambda/serverless
- Only relevant if running EC2 instances

---

## Cost Comparison: Haiku vs Sonnet

### Real Example: Processing 30,000 emails/month

**Scenario:** Each email requires:
- 500 input tokens (email + context)
- 200 output tokens (response)

#### Claude 3 Haiku (Current)
```
Input:  30,000 emails × 500 tokens = 15M tokens
        15M × $0.25/1M = $3.75

Output: 30,000 emails × 200 tokens = 6M tokens
        6M × $1.25/1M = $7.50

Total: $11.25/month
```

#### Claude 3 Sonnet (Previous)
```
Input:  15M × $3.00/1M = $45.00
Output: 6M × $15.00/1M = $90.00

Total: $135.00/month
```

**Savings by switching to Haiku: $123.75/month** ✅

---

## Emergency Cost Controls

### If costs exceed budget:

#### 1. Reduce Processing Volume
```bash
# Update confidence threshold (only process high-confidence)
# In terraform.tfvars or Lambda env vars
MIN_CONFIDENCE_TO_PROCESS = 0.9  # Instead of 0.8
```

#### 2. Disable Non-Critical Features
```bash
# Disable multi-LLM benchmarking (runs extra models)
# Comment out parallel intent classification
# Use single model only
```

#### 3. Reduce Log Retention
```hcl
# In terraform/variables.tf
log_retention_days = 1  # Instead of 7
```

#### 4. Archive Old Data Immediately
```bash
# Move to Glacier immediately (not after 90 days)
aws s3 cp s3://bucket/emails/ s3://bucket/emails-archive/ \
  --recursive --storage-class GLACIER
```

---

## ROI Calculation

### Cost per Email

**With Claude 3 Haiku:**
- Total cost: $0.0006 per email
- Staff time saved: 5 minutes per email
- Staff cost: ~$30/hour = $2.50 per email
- **ROI: $2.50 / $0.0006 = 4,167:1**

### Break-Even Analysis

**Monthly costs: $19**
- Emails processed: 30,000
- Staff time saved: 2,500 hours
- At $30/hour: $75,000 in savings
- **Net savings: $74,981/month**

---

## Cost Optimization Checklist

- [x] Use Claude 3 Haiku instead of Sonnet/Opus
- [x] DynamoDB PAY_PER_REQUEST mode
- [x] S3 lifecycle rules (90 days → Glacier)
- [x] CloudWatch logs 7-day retention
- [x] Lambda memory right-sized
- [x] Confidence thresholds to reduce volume
- [x] Truncate prompts to reduce tokens
- [x] Limit RAG context to top 3 documents
- [ ] Set up billing alerts
- [ ] Tag all resources for cost tracking
- [ ] Monthly cost review
- [ ] Consider caching for similar emails
- [ ] Batch processing for non-urgent emails

---

## Frequently Asked Questions

### Q: Can we use completely free models?

**A:** AWS Bedrock doesn't offer completely free models. All models are pay-per-use. However:
- AWS Free Tier: 12 months of free Lambda, S3, DynamoDB (limited)
- Bedrock Free Trial: Some regions offer limited free trial credits
- **Current setup is already using the cheapest viable option (Haiku)**

### Q: Why not use open-source models like Llama?

**A:**
- Llama 3 on Bedrock costs similar to Haiku
- Running self-hosted models on EC2 is more expensive
- We'd need to:
  - Pay for EC2 instances 24/7 (~$100/month minimum)
  - Manage infrastructure
  - Handle scaling
- **Bedrock + Haiku is most cost-effective**

### Q: Can we reduce costs to under $10/month?

**A:** Yes, for low volume:
- Process <500 emails/day: ~$5/month
- Process <100 emails/day: ~$2/month
- Most services have free tiers at low volume

### Q: What if we only want to process business hours?

**A:**
- Lambda/Bedrock only charge when used
- No need to disable anything
- Costs automatically scale to zero when idle

---

## Summary

### Current Optimization Status

✅ **Already Optimized:**
- Using Claude 3 Haiku (cheapest capable model)
- DynamoDB PAY_PER_REQUEST (no idle costs)
- S3 lifecycle rules (automatic archival)
- Right-sized Lambda memory
- 7-day log retention
- Confidence-based routing

### Cost Targets

| Volume | Current | Optimized | Savings |
|--------|---------|-----------|---------|
| 100/day | $2 | $2 | $0 (already optimal) |
| 1,000/day | $19 | $19 | $0 (already optimal) |
| 10,000/day | $179 | $150 | $29 (with caching) |

### Next Steps

1. **Monitor costs**: Set up billing alerts
2. **Review monthly**: Check AWS Cost Explorer
3. **Consider caching**: If >30% similar emails
4. **Scale appropriately**: Costs scale linearly with volume

**Bottom line:** Current setup is already cost-optimized for the free/cheap tier. Claude 3 Haiku provides excellent value at ~$0.0004 per email.
