# InsureMail AI - Deployment Guide

## Prerequisites

### Required Software
- AWS CLI v2 (configured with credentials)
- Terraform >= 1.0
- Python >= 3.11
- Git

### AWS Account Requirements
- AWS Account with admin access
- Bedrock access enabled in your region (us-east-1 recommended)
- Sufficient service limits for:
  - Lambda functions (6)
  - DynamoDB tables (3)
  - S3 buckets (3)
  - Step Functions (1)

## Step-by-Step Deployment

### 1. Enable Bedrock Model Access

**CRITICAL**: This step must be done manually before deployment.

1. Go to [AWS Bedrock Console](https://console.aws.amazon.com/bedrock/)
2. Navigate to "Model access" in the left sidebar
3. Click "Manage model access"
4. Request access for the following models:
   - **Anthropic Claude 3 Sonnet** (anthropic.claude-3-sonnet-20240229-v1:0)
   - **Anthropic Claude 3 Haiku** (anthropic.claude-3-haiku-20240307-v1:0)
   - **Amazon Titan Text Lite** (amazon.titan-text-lite-v1)
   - **Amazon Titan Embeddings** (amazon.titan-embed-text-v1)
   - **Meta Llama 3 8B** (meta.llama3-8b-instruct-v1:0) - Optional
   - **Mistral 7B** (mistral.mistral-7b-instruct-v0:2) - Optional

5. Wait for approval (typically instant for Claude and Titan)

### 2. Configure AWS Credentials

```bash
# Set AWS profile (if using multiple profiles)
export AWS_PROFILE=your-profile

# Set AWS region
export AWS_REGION=us-east-1

# Verify credentials
aws sts get-caller-identity
```

### 3. Deploy Infrastructure

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

### 4. Upload Test Data

```bash
# Upload knowledge base and sample emails
./scripts/upload_test_data.sh
```

This will:
- Upload 3 knowledge base documents to S3
- Trigger RAG ingestion Lambda
- Upload 3 sample emails
- Trigger email parsing Lambda

### 5. Test the Pipeline

```bash
# Run end-to-end tests
./scripts/test_pipeline.sh
```

This will:
- Verify knowledge base is populated
- Check parsed emails in DynamoDB
- Optionally trigger Step Functions workflow
- Provide CloudWatch Logs links

## Architecture Overview

```
Email (S3) → Email Parser (Lambda) → Step Functions
                                         ↓
                          ┌──────────────┴────────────────┐
                          │                               │
                    Intent Classification         Entity Extraction
                     (Multi-LLM Lambda)           (Simplified)
                          │                               │
                          └──────────────┬────────────────┘
                                         ↓
                              RAG Retrieval (Lambda)
                                         ↓
                              CRM Validation (Mock)
                                         ↓
                              Fraud Assessment (Rules)
                                         ↓
                          Claude Response Generation (Lambda)
                                         ↓
                        ┌────────────────┼────────────────┐
                        │                │                │
                   Auto-respond    Human Review      Escalate
                   (≥0.8 conf)    (0.5-0.8 conf)   (<0.5 conf)
```

## Resource Naming Convention

All resources use the pattern: `{project_name}-{environment}-{resource_type}`

Example: `insuremail-ai-dev-email-parser`

## Monitoring and Troubleshooting

### CloudWatch Logs

- **Lambda Functions**: `/aws/lambda/insuremail-ai-dev-*`
- **Step Functions**: `/aws/vendedlogs/states/insuremail-ai-dev-email-processing`

### CloudWatch Dashboard

View in AWS Console:
```
https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=insuremail-ai-dev-dashboard
```

### Common Issues

**Issue**: Lambda timeout errors
- **Solution**: Increase timeout in `terraform/modules/lambda/main.tf`

**Issue**: Bedrock throttling errors
- **Solution**: Implement exponential backoff or request limit increase

**Issue**: No embeddings in knowledge base
- **Solution**: Check RAG ingestion Lambda logs; verify S3 trigger is configured

**Issue**: Step Functions fails at Claude response step
- **Solution**: Verify Bedrock model access is enabled; check IAM permissions

## Cost Estimation

### Free Tier Usage
- Lambda: 1M requests/month free
- DynamoDB: 25 GB storage free
- S3: 5 GB storage free
- Step Functions: 4,000 state transitions free

### Expected Costs (After Free Tier)
- Bedrock API calls: ~$0.003 per email (Claude 3 Sonnet)
- Lambda: ~$0.20 per 1M invocations
- DynamoDB: Pay-per-request (minimal for demo)
- S3: ~$0.023 per GB/month

**Estimated total for 1,000 emails**: $3-5 USD

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

## Next Steps

1. **Dashboard Development**: Build React frontend (see `dashboard/`)
2. **API Gateway**: Add REST API for external access
3. **Authentication**: Integrate Cognito for dashboard
4. **Production Hardening**:
   - Add VPC configuration
   - Implement secrets management (AWS Secrets Manager)
   - Set up CI/CD pipeline
   - Configure backup policies
   - Add monitoring alerts (SNS)

## Support

For issues or questions:
- Check CloudWatch Logs first
- Review Terraform state: `terraform show`
- Verify IAM permissions
- Confirm Bedrock model access

## Security Best Practices

✅ **Implemented**:
- IAM least-privilege policies
- S3 encryption at rest
- DynamoDB encryption
- VPC endpoints (optional - not in demo)
- PII redaction in logs

⚠️ **TODO for Production**:
- Enable MFA for AWS accounts
- Rotate IAM credentials regularly
- Implement AWS WAF for API Gateway
- Set up AWS Config for compliance
- Enable AWS GuardDuty for threat detection
