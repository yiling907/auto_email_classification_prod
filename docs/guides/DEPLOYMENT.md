# InsureMail AI - Complete Deployment Guide

Comprehensive guide for deploying the full InsureMail AI system (infrastructure + dashboard).

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Infrastructure Deployment](#infrastructure-deployment)
3. [Dashboard Deployment](#dashboard-deployment)
4. [Email Integration](#email-integration)
5. [Testing & Validation](#testing--validation)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software
- **AWS CLI v2** (configured with credentials)
- **Terraform** >= 1.0
- **Python** >= 3.11
- **Node.js** >= 18 (for dashboard)
- **Git**

### AWS Account Requirements
- AWS Account with admin access
- Bedrock access enabled in your region (us-east-1 recommended)
- Sufficient service limits for:
  - Lambda functions (9)
  - DynamoDB tables (3)
  - S3 buckets (3)
  - Step Functions (1)
  - EventBridge rules (2)

### Configure AWS Credentials

```bash
# Set AWS profile (if using multiple profiles)
export AWS_PROFILE=your-profile

# Set AWS region
export AWS_REGION=us-east-1

# Verify credentials
aws sts get-caller-identity
```

---

## Infrastructure Deployment

### Step 1: Enable Bedrock Model Access

**CRITICAL**: This step must be done manually before deployment.

1. Go to [AWS Bedrock Console](https://console.aws.amazon.com/bedrock/)
2. Navigate to "Model access" in the left sidebar
3. Click "Manage model access"
4. Request access for the following models:
   - **Mistral 7B Instruct** (mistral.mistral-7b-instruct-v0:2) - Primary model
   - **Meta Llama 3.1 8B** (us.meta.llama3-1-8b-instruct-v1:0) - Fallback
   - **Amazon Titan Embeddings** (amazon.titan-embed-text-v1) - RAG
   - **Anthropic Claude 3 Haiku** (optional) - High-quality responses

5. Wait for approval (typically instant for Mistral and Titan)

### Step 2: Deploy Infrastructure

#### Option A: Automated Script (Recommended)

```bash
# Run deployment script
./scripts/deploy_terraform.sh
```

This script will:
- Initialize Terraform
- Validate configuration
- Create execution plan
- Apply infrastructure (after confirmation)

**Expected deployment time**: 5-10 minutes

#### Option B: Manual Deployment

```bash
cd terraform

# Initialize Terraform
terraform init

# Review planned changes
terraform plan

# Deploy infrastructure
terraform apply
```

### Step 3: Verify Infrastructure Deployment

```bash
# Check all resources
terraform state list | wc -l

# Get key outputs
terraform output lambda_functions
terraform output step_functions_arn
terraform output api_gateway_url

# Test Lambda function
aws lambda invoke \
  --function-name insuremail-ai-dev-email-parser \
  --payload '{"test": true}' \
  output.json
```

---

## Dashboard Deployment

### Quick Start

#### One-Command Deployment

```bash
./scripts/deploy_dashboard.sh
```

This script will:
1. ✅ Get API Gateway URL from Terraform
2. ✅ Install npm dependencies (if needed)
3. ✅ Create `.env` file with API URL
4. ✅ Build the React application
5. ✅ Ask if you want to deploy to S3
6. ✅ Deploy to S3 (new or existing bucket)
7. ✅ Enable static website hosting
8. ✅ Configure public access
9. ✅ Optionally set up CloudFront CDN
10. ✅ Provide the dashboard URL

### Deployment Options

#### Option 1: Deploy to New S3 Bucket (Recommended)

```bash
./scripts/deploy_dashboard.sh

# Select: 1) Deploy to S3 (new bucket)
# Enter bucket name (or press Enter for auto-generated name)
# Enter AWS region (default: us-east-1)
```

**What happens:**
- Creates S3 bucket
- Uploads built files
- Enables static website hosting
- Configures bucket policy for public access
- Provides website URL

**Example Output:**
```
Dashboard URL:
  http://insuremail-ai-dashboard.s3-website-us-east-1.amazonaws.com
```

#### Option 2: Deploy to Existing S3 Bucket

```bash
./scripts/deploy_dashboard.sh

# Select: 2) Deploy to S3 (existing bucket)
# Enter your bucket name
# Enter AWS region
```

#### Option 3: Build Only (No Deployment)

```bash
./scripts/deploy_dashboard.sh

# Select: 3) Skip deployment (build only)
```

Build output will be in `dashboard/frontend/dist/`

### CloudFront Setup (Optional)

After deploying to S3, the script offers to set up CloudFront CDN:

```
Would you like to set up CloudFront CDN now? (y/n): y
```

**Benefits of CloudFront:**
- ✅ HTTPS enabled by default
- ✅ Global CDN for faster loading
- ✅ Better security (DDoS protection)
- ✅ Custom domain support
- ✅ SSL/TLS certificates

**Note:** CloudFront distribution takes 10-15 minutes to deploy.

### Manual Dashboard Deployment

If you prefer to deploy manually:

#### Step 1: Build Dashboard

```bash
cd dashboard/frontend

# Install dependencies
npm install

# Get API URL
API_URL=$(cd ../../terraform && terraform output -raw api_gateway_url)

# Create .env file
echo "VITE_API_BASE_URL=$API_URL" > .env

# Build
npm run build
```

#### Step 2: Create S3 Bucket

```bash
# Set variables
BUCKET_NAME="my-insuremail-dashboard"
REGION="us-east-1"

# Create bucket
aws s3 mb s3://$BUCKET_NAME --region $REGION
```

#### Step 3: Upload Files

```bash
# Upload all files with public-read ACL
aws s3 sync dist/ s3://$BUCKET_NAME/ --delete --acl public-read
```

#### Step 4: Enable Static Website Hosting

```bash
aws s3 website s3://$BUCKET_NAME \
  --index-document index.html \
  --error-document index.html
```

#### Step 5: Configure Public Access

```bash
aws s3api put-public-access-block \
  --bucket $BUCKET_NAME \
  --public-access-block-configuration \
  "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"
```

---

## Email Integration

### SES Setup

See **[SES_SETUP.md](./SES_SETUP.md)** for detailed email configuration.

#### Quick Setup

```bash
# Run SES setup script
./scripts/setup_ses.sh
```

This will:
- Verify sender email addresses
- Create receipt rule for incoming emails
- Configure SNS topic subscription
- Test email receiving

#### SES Sandbox Mode

**IMPORTANT**: New AWS accounts start in SES sandbox mode, which means:
- ❌ Can only send TO verified email addresses
- ❌ Cannot receive emails from unverified senders
- ✅ Can still test the full workflow manually

**Solutions:**
1. **Verify all test email addresses** (quick, for testing)
2. **Request production access** (removes restrictions, 24-48 hrs)
3. **Use simulation script** (bypass SES entirely for testing)

See **[SES_LIMITATIONS.md](../troubleshooting/SES_LIMITATIONS.md)** for details.

---

## Testing & Validation

### Upload Test Data

```bash
# Upload knowledge base and sample emails
./scripts/upload_test_data.sh
```

This will:
- Upload 3 knowledge base documents to S3
- Trigger RAG ingestion Lambda
- Upload 3 sample emails
- Trigger email parsing Lambda

### Test Email Workflow

#### Option 1: Real Email (SES Production Mode Required)

```bash
# Send email to your SES-configured address
echo "Test email body" | mail -s "Test Subject" your-ses-address@yourdomain.com
```

#### Option 2: Simulated Email (Works in Sandbox Mode)

```bash
# Use simulation script
bash scripts/simulate_email_workflow.sh
```

This script:
- Prompts for email details
- Uploads to S3 manually
- Triggers Step Functions workflow
- Monitors execution
- Displays results

### Run Automated Tests

```bash
# Run full test suite
make test

# Run specific tests
make test-unit
make test-integration
make test-terraform
```

See **[tests/README.md](../../tests/README.md)** for complete testing guide.

### Monitor Execution

```bash
# View Step Functions execution
aws stepfunctions list-executions \
  --state-machine-arn $(terraform output -raw step_functions_arn) \
  --max-items 5

# View Lambda logs
aws logs tail /aws/lambda/insuremail-ai-dev-email-parser --follow
aws logs tail /aws/lambda/insuremail-ai-dev-multi-llm-inference --follow
aws logs tail /aws/lambda/insuremail-ai-dev-claude-response --follow

# Check model metrics
aws lambda invoke \
  --function-name insuremail-ai-dev-evaluation-metrics \
  --payload '{"task_type":"all","days":7}' \
  output.json && cat output.json | jq '.statistics'
```

---

## Architecture Overview

```
Email (SES)
  → SNS Topic (ses-notifications)
    → Email Receiver Lambda
      → Step Functions Workflow
        ├─ Email Parsing
        ├─ Intent Classification (Multi-LLM)
        ├─ Entity Extraction (Multi-LLM)
        ├─ RAG Retrieval (Titan Embeddings)
        ├─ CRM Validation (Mock)
        ├─ Fraud Scoring (Rule-based)
        └─ Response Generation (Mistral/Llama)
          → Auto-Send or Human Review

Evaluation Metrics (Separate):
  ← EventBridge Schedule (Daily/Weekly)
  ← API Handlers (Dashboard queries)
  → Model Performance Statistics
```

### Resource Naming Convention

All resources use the pattern: `{project_name}-{environment}-{resource_type}`

Example: `insuremail-ai-dev-email-parser`

---

## Troubleshooting

### Lambda Timeout Errors

**Solution**: Increase timeout in `terraform/modules/lambda/main.tf`

```hcl
resource "aws_lambda_function" "..." {
  timeout = 300  # Increase from default 30s
}
```

### Bedrock Throttling Errors

**Solution**: Implement exponential backoff or request limit increase

### No Embeddings in Knowledge Base

**Solution**: Check RAG ingestion Lambda logs; verify S3 trigger is configured

```bash
aws logs tail /aws/lambda/insuremail-ai-dev-rag-ingestion --since 10m
```

### Step Functions Fails at Claude Response Step

**Solution**: Verify Bedrock model access is enabled; check IAM permissions

```bash
# Check IAM policy
aws iam get-role-policy \
  --role-name insuremail-ai-dev-lambda-execution \
  --policy-name insuremail-ai-dev-bedrock-access
```

### Dashboard Shows 404 Errors

**Solutions:**
1. Check bucket policy is applied
2. Verify public access block settings
3. Ensure files have public-read ACL
4. Check bucket name in URL is correct

```bash
# Fix public access
aws s3api put-public-access-block \
  --bucket $BUCKET_NAME \
  --public-access-block-configuration \
  "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"

# Re-upload with public-read
aws s3 sync dist/ s3://$BUCKET_NAME/ --delete --acl public-read
```

### API Not Working (CORS Errors)

**Solutions:**
1. Verify API Gateway is deployed
2. Check `.env` file has correct API URL
3. Ensure API Gateway has CORS enabled
4. Check browser console for specific errors

```bash
# Verify API URL
cd terraform
terraform output api_gateway_url

# Test API endpoint
curl $(terraform output -raw api_gateway_url)/api/dashboard/overview
```

---

## Cost Estimation

### Free Tier Usage
- Lambda: 1M requests/month free
- DynamoDB: 25 GB storage free
- S3: 5 GB storage free
- Step Functions: 4,000 state transitions free

### Expected Costs (After Free Tier)

**Monthly Estimates:**
- **100 emails/day**: ~$2/month
- **1,000 emails/day**: ~$19/month
- **10,000 emails/day**: ~$179/month

**Breakdown:**
- Bedrock API calls: ~$0.015 per email (Mistral 7B)
- Lambda: ~$0.20 per 1M invocations
- DynamoDB: Pay-per-request (minimal for demo)
- S3: ~$0.023 per GB/month
- Dashboard (S3): <$1/month
- Dashboard (CloudFront): $5-20/month

See **[COST_OPTIMIZATION.md](../reference/COST_OPTIMIZATION.md)** for detailed analysis.

---

## Security Best Practices

### ✅ Implemented
- IAM least-privilege policies
- S3 encryption at rest
- DynamoDB encryption
- PII redaction in logs
- Public access controls

### ⚠️ TODO for Production
- Enable MFA for AWS accounts
- Rotate IAM credentials regularly
- Implement AWS WAF for API Gateway
- Set up AWS Config for compliance
- Enable AWS GuardDuty for threat detection
- Use AWS Secrets Manager for sensitive data
- Configure VPC for Lambda functions

---

## Cleanup

To destroy all resources:

```bash
cd terraform
terraform destroy
```

**WARNING**: This will delete all data including:
- S3 buckets and contents
- DynamoDB tables and data
- All Lambda functions
- Step Functions state machine
- EventBridge rules
- Dashboard bucket

---

## Next Steps

### Immediate
1. ✅ Verify all Lambda functions deployed
2. ✅ Test email workflow with simulation script
3. ✅ Access dashboard and verify API connectivity
4. ✅ Upload knowledge base documents
5. ✅ Run evaluation metrics

### Short-term
1. Request SES production access (remove sandbox limitations)
2. Set up custom domain for dashboard
3. Enable CloudWatch alarms
4. Configure backup policies
5. Add monitoring dashboards

### Long-term
1. **Production Deployment**:
   - Change environment from "dev" to "prod"
   - Enable VPC configuration
   - Implement secrets management
   - Set up CI/CD pipeline

2. **Advanced Features**:
   - Add sentiment analysis
   - Implement A/B testing for model selection
   - Build feedback loop for model improvement
   - Add multilingual support

See **[ROADMAP.md](../ROADMAP.md)** for complete feature roadmap.

---

## Support

- **Documentation**: See `/docs` folder for detailed guides
- **Logs**: CloudWatch Logs - Filter by `/aws/lambda/insuremail-ai-dev-*`
- **State**: Terraform state in S3 backend
- **Issues**: Check AWS console for resource-specific errors

---

## Resources

- [AWS Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/)
- [Amazon SES Developer Guide](https://docs.aws.amazon.com/ses/)

---

**Deployment Status**: Ready for production (after SES production access)
**Last Updated**: March 4, 2026
