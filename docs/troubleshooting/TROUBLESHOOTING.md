# InsureMail AI - Troubleshooting Guide

Common issues and solutions for the InsureMail AI system.

---

## Quick Diagnostics

### Check System Health

```bash
# Verify Lambda functions
aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `insuremail-ai-dev`)].FunctionName'

# Check Step Functions executions
aws stepfunctions list-executions \
  --state-machine-arn $(cd terraform && terraform output -raw step_functions_arn) \
  --max-items 5

# Test evaluation metrics
aws lambda invoke \
  --function-name insuremail-ai-dev-evaluation-metrics \
  --payload '{"task_type":"all","days":7}' \
  output.json

# Check CloudWatch logs
aws logs tail /aws/lambda/insuremail-ai-dev-email-parser --since 10m
```

---

## Lambda Issues

### Lambda Timeout Errors

**Symptoms:** Lambda execution exceeds time limit, function terminates

**Causes:**
- Bedrock API calls taking too long
- Large documents in RAG retrieval
- Network latency

**Solutions:**

```bash
# Increase timeout in Terraform
# File: terraform/modules/lambda/main.tf
```

```hcl
resource "aws_lambda_function" "example" {
  timeout = 300  # Increase from default 30s
}
```

Apply changes:
```bash
cd terraform
terraform apply -target=module.lambda
```

### Lambda Out of Memory

**Symptoms:** Function logs show memory exhaustion, crashes

**Solutions:**

```hcl
# Increase memory allocation
resource "aws_lambda_function" "example" {
  memory_size = 512  # Increase from 256 MB
}
```

### Lambda Permission Errors

**Symptoms:** `AccessDeniedException` in CloudWatch logs

**Check IAM policy:**

```bash
aws iam get-role-policy \
  --role-name insuremail-ai-dev-lambda-execution \
  --policy-name insuremail-ai-dev-bedrock-access
```

**Fix:** Verify Bedrock model access in IAM policy includes inference profiles:

```json
{
  "Resource": [
    "arn:aws:bedrock:*::foundation-model/*",
    "arn:aws:bedrock:*:*:inference-profile/*"
  ]
}
```

---

## Bedrock Issues

### Bedrock Model Not Found

**Symptoms:** `ValidationException: The provided model identifier is invalid`

**Causes:**
- Model not enabled in region
- Incorrect model ID
- Model access not granted

**Solutions:**

1. **Check model availability:**
```bash
aws bedrock list-foundation-models --region us-east-1 \
  --query 'modelSummaries[?contains(modelId, `mistral`)].modelId'
```

2. **Verify model access:**
   - Go to AWS Bedrock Console
   - Check "Model access" page
   - Ensure models are enabled

3. **Update model IDs:**
   - Mistral 7B: `mistral.mistral-7b-instruct-v0:2`
   - Llama 3.1 8B: `us.meta.llama3-1-8b-instruct-v1:0` (inference profile)
   - Titan Embeddings: `amazon.titan-embed-text-v1`

### Bedrock Throttling

**Symptoms:** `ThrottlingException: Rate exceeded`

**Solutions:**

1. **Implement retry logic with exponential backoff:**

```python
import time
from botocore.exceptions import ClientError

def invoke_with_retry(bedrock_client, **kwargs):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return bedrock_client.invoke_model(**kwargs)
        except ClientError as e:
            if e.response['Error']['Code'] == 'ThrottlingException':
                wait_time = (2 ** attempt) * 0.1
                time.sleep(wait_time)
            else:
                raise
    raise Exception("Max retries exceeded")
```

2. **Request quota increase:**
   - Go to AWS Service Quotas console
   - Search for "Bedrock"
   - Request increase for model invocations

---

## DynamoDB Issues

### Float Type Error

**Symptoms:** `'decimal.Context' object has no attribute 'create_type_serializer'`

**Cause:** DynamoDB doesn't support Python float type

**Solution:** Convert floats to Decimal before storing:

```python
from decimal import Decimal

# Correct way
item = {
    'latency_ms': Decimal(str(123.45)),
    'cost_usd': Decimal(str(0.0015))
}
table.put_item(Item=item)
```

### Embedding Storage Error

**Symptoms:** Cannot serialize float arrays

**Cause:** DynamoDB doesn't support lists of floats

**Solution:** Convert to JSON string:

```python
import json

# Store embeddings as JSON string
item = {
    'embedding': json.dumps([0.1, 0.2, 0.3])
}

# Read and parse
embedding = json.loads(item['embedding'])
```

See: [METRICS_STORAGE_BUG_FIX.md](../historical/METRICS_STORAGE_BUG_FIX.md)

---

## RAG Issues

### No Documents Retrieved

**Symptoms:** RAG retrieval returns empty results

**Diagnostic:**

```bash
# Check if embeddings exist
aws dynamodb scan \
  --table-name insuremail-ai-dev-embeddings \
  --max-items 1
```

**Solutions:**

1. **Re-upload knowledge base:**
```bash
./scripts/upload_knowledge_base.sh
```

2. **Check S3 trigger:**
```bash
aws s3api get-bucket-notification-configuration \
  --bucket insuremail-ai-dev-knowledge-base
```

3. **Verify RAG ingestion logs:**
```bash
aws logs tail /aws/lambda/insuremail-ai-dev-rag-ingestion --since 30m
```

### Low Similarity Scores

**Symptoms:** Retrieved documents have low relevance

**Solutions:**

1. **Improve document chunking:**
   - Reduce chunk size for more granular retrieval
   - Increase overlap for better context

2. **Enhance document quality:**
   - Add metadata to documents
   - Use clear section headers
   - Include relevant keywords

3. **Adjust similarity threshold:**
```python
# In rag_retrieval lambda_function.py
MIN_SIMILARITY_THRESHOLD = 0.3  # Lower for more results
```

---

## Step Functions Issues

### Workflow Execution Fails

**Symptoms:** Step Functions shows FAILED status

**Diagnostic:**

```bash
# Get execution details
EXECUTION_ARN="your-execution-arn"
aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN

# Get execution history
aws stepfunctions get-execution-history --execution-arn $EXECUTION_ARN
```

**Common Causes:**

1. **Lambda function errors** - Check CloudWatch logs
2. **Timeout issues** - Increase Lambda timeouts
3. **IAM permissions** - Verify Step Functions can invoke Lambdas
4. **Input validation** - Check state machine input format

### Workflow Stuck in RUNNING

**Symptoms:** Execution never completes

**Solutions:**

1. **Check for infinite loops** in state machine definition
2. **Verify Choice state conditions** are reachable
3. **Add timeout to state machine:**

```json
{
  "TimeoutSeconds": 300,
  "States": { ... }
}
```

---

## Email Integration Issues

### Emails Not Triggering Workflow

**Symptoms:** No Step Functions execution when email received

**See:** [SES_LIMITATIONS.md](./SES_LIMITATIONS.md) for Gmail-to-Gmail issue

**Diagnostic:**

```bash
# Check SES receipt rule
aws ses describe-receipt-rule \
  --rule-set-name default-rule-set \
  --rule-name insuremail-ai-dev-receipt-rule

# Check SNS topic subscription
aws sns list-subscriptions-by-topic \
  --topic-arn $(cd terraform && terraform output -raw sns_topic_arn)

# Check S3 bucket for emails
aws s3 ls s3://insuremail-ai-dev-emails/incoming/
```

**Solutions:**

1. **Use simulation script:**
```bash
bash scripts/simulate_email_workflow.sh
```

2. **Set up custom domain** - See [SES_LIMITATIONS.md](./SES_LIMITATIONS.md)

3. **Verify SNS subscription is confirmed:**
```bash
aws sns get-subscription-attributes \
  --subscription-arn YOUR-SUBSCRIPTION-ARN
```

### SES Sandbox Mode Restrictions

**Symptoms:** `Email address is not verified` error

**Solutions:**

1. **Quick fix - Verify recipient:**
```bash
aws ses verify-email-identity --email-address recipient@example.com
# Check email and click verification link
```

2. **Long-term - Request production access:**
```bash
./scripts/request_production_access.sh
```

Or manually:
- Go to SES Console → Account Dashboard
- Click "Request production access"
- Typically approved in 24-48 hours

---

## Dashboard Issues

### Dashboard Shows 403 Forbidden

**Symptoms:** Cannot access S3 website, getting 403 error

**Solutions:**

```bash
BUCKET_NAME="your-bucket-name"

# Fix public access block
aws s3api put-public-access-block \
  --bucket $BUCKET_NAME \
  --public-access-block-configuration \
  "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"

# Verify bucket policy
aws s3api get-bucket-policy --bucket $BUCKET_NAME

# Re-upload files with public-read
cd dashboard/frontend
aws s3 sync dist/ s3://$BUCKET_NAME/ --delete --acl public-read
```

### Dashboard API Not Working (CORS)

**Symptoms:** Dashboard loads but shows no data, CORS errors in console

**Solutions:**

1. **Verify API Gateway URL:**
```bash
cd terraform
terraform output api_gateway_url
```

2. **Check .env file:**
```bash
cd dashboard/frontend
cat .env
# Should show: VITE_API_BASE_URL=https://your-api-url
```

3. **Test API directly:**
```bash
curl $(cd terraform && terraform output -raw api_gateway_url)/api/dashboard/overview
```

4. **Verify CORS in API Gateway:**
   - Go to API Gateway console
   - Check OPTIONS method has proper CORS headers

### Old Content Showing After Update

**Symptoms:** Dashboard not showing latest changes

**Solutions:**

For S3 only:
```bash
# Clear browser cache (Ctrl+Shift+R / Cmd+Shift+R)
```

For CloudFront:
```bash
# Invalidate CloudFront cache
DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[0].Id" --output text)
aws cloudfront create-invalidation --distribution-id $DIST_ID --paths "/*"
```

---

## Testing Issues

### Tests Fail Locally

**Symptoms:** Tests pass in CI but fail locally

**Solutions:**

```bash
# Clean cache
make clean

# Reinstall dependencies
cd tests
pip install -r requirements.txt

# Run tests again
make test
```

### Import Errors in Tests

**Symptoms:** `ModuleNotFoundError: No module named 'lambda_function'`

**Solution:** Tests automatically add Lambda directories to path. Verify:

```python
# In test file
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/function_name'))
```

### AWS Credentials Error in Tests

**Symptoms:** Tests fail with AWS credentials error

**Solution:** Tests use moto for mocking. Ensure fixture is used:

```python
@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'testing')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'testing')
```

---

## Performance Issues

### Slow Response Times

**Symptoms:** Email processing takes >60 seconds

**Diagnostic:**

```bash
# Check latency metrics
aws lambda invoke \
  --function-name insuremail-ai-dev-evaluation-metrics \
  --payload '{"task_type":"all","days":1}' \
  output.json

cat output.json | jq '.statistics.by_model[].average_latency_ms'
```

**Solutions:**

1. **Use faster models:**
   - Mistral 7B: ~3-5 seconds
   - Llama 3.1 8B: ~5-8 seconds

2. **Optimize RAG retrieval:**
   - Reduce number of documents retrieved
   - Pre-filter by metadata
   - Use smaller embeddings

3. **Parallelize where possible:**
   - Intent + entity extraction run in parallel
   - Consider parallel RAG queries

### High Costs

**Symptoms:** AWS bill higher than expected

**Diagnostic:**

```bash
# Check Bedrock usage
aws ce get-cost-and-usage \
  --time-period Start=2026-03-01,End=2026-03-31 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --filter file://filter.json

# filter.json:
{
  "Dimensions": {
    "Key": "SERVICE",
    "Values": ["Amazon Bedrock"]
  }
}
```

**Solutions:**

1. **Switch to cheaper models** - See [COST_OPTIMIZATION.md](../reference/COST_OPTIMIZATION.md)
2. **Implement caching** for repeated queries
3. **Reduce token usage** with prompt optimization
4. **Set up cost alerts** in AWS Budgets

---

## Common Error Messages

### "Float types are not supported. Use Decimal types instead."

**Fix:** See [METRICS_STORAGE_BUG_FIX.md](../historical/METRICS_STORAGE_BUG_FIX.md)

```python
from decimal import Decimal
item = {'value': Decimal(str(123.45))}
```

### "The provided model identifier is invalid"

**Fix:** Check model ID and region availability

```bash
# List available models
aws bedrock list-foundation-models --region us-east-1
```

### "AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel"

**Fix:** Update IAM policy to include Bedrock permissions

```bash
cd terraform
terraform apply -target=module.iam
```

### "Email address is not verified"

**Fix:** Verify email or request SES production access

```bash
aws ses verify-email-identity --email-address user@example.com
```

### "Rate exceeded"

**Fix:** Implement retry logic or request quota increase

---

## Getting Help

### 1. Check Logs First

```bash
# Lambda logs
aws logs tail /aws/lambda/insuremail-ai-dev-FUNCTION-NAME --follow

# Step Functions execution
aws stepfunctions describe-execution --execution-arn EXECUTION-ARN
```

### 2. Review Documentation

- [Deployment Guide](../guides/DEPLOYMENT.md)
- [SES Setup](../guides/SES_SETUP.md)
- [Testing Guide](../../tests/README.md)

### 3. Check AWS Service Health

- [AWS Service Health Dashboard](https://health.aws.amazon.com/health/status)

### 4. Verify Configuration

```bash
# Review Terraform outputs
cd terraform
terraform output

# Check resource state
terraform show
```

---

## Debug Mode

Enable verbose logging:

```python
# In Lambda function code
import logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

logger.debug(f"Detailed info: {variable}")
```

Redeploy:
```bash
cd terraform
terraform apply -target=module.lambda
```

---

**Last Updated**: March 4, 2026

**See Also:**
- [SES_LIMITATIONS.md](./SES_LIMITATIONS.md) - Email receiving issues
- [Deployment Guide](../guides/DEPLOYMENT.md) - Setup and deployment
- [Testing Guide](../../tests/README.md) - Running tests
