# InsureMail AI — Deployment Guide

This document covers every deployment path: full infrastructure from scratch,
incremental Lambda code updates, frontend deploys, and Step Functions changes.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [First-Time Full Deploy](#2-first-time-full-deploy)
3. [Incremental Lambda Deploy](#3-incremental-lambda-deploy)
4. [Frontend Deploy](#4-frontend-deploy)
5. [Step Functions Deploy](#5-step-functions-deploy)
6. [Knowledge Base Upload](#6-knowledge-base-upload)
7. [Verify Deployment](#7-verify-deployment)
8. [Environment Reference](#8-environment-reference)
9. [Rollback](#9-rollback)

---

## 1. Prerequisites

| Tool | Min version | Check |
|------|------------|-------|
| AWS CLI | v2 | `aws --version` |
| Terraform | 1.0+ | `terraform --version` |
| Python | 3.11+ | `python3 --version` |
| Node.js | 18+ | `node --version` |
| zip | any | `zip --version` |

**AWS credentials**:
```bash
export AWS_PROFILE=your-profile   # or set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY
export AWS_REGION=us-east-1

# Verify
aws sts get-caller-identity
```

**Required Bedrock model access** (enable once in AWS Console → Bedrock → Model access):
- Amazon Titan Embeddings (`amazon.titan-embed-text-v1`)
- Mistral 7B Instruct (`mistral.mistral-7b-instruct-v0:2`)
- Llama 3.1 8B Instruct (`meta.llama3-8b-instruct-v1:0`)

---

## 2. First-Time Full Deploy

### 2.1 Configure variables

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform/terraform.tfvars — set project_name, environment, region, etc.
```

### 2.2 Deploy infrastructure

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

Key outputs saved after apply:

| Output | Value |
|--------|-------|
| `api_gateway_url` | Dashboard API base URL |
| `email_bucket_name` | Raw email storage |
| `knowledge_base_bucket_name` | RAG document storage |
| `state_machine_arn` | Step Functions ARN |
| `lambda_functions` | Map of function ARNs |

### 2.3 Upload knowledge base documents

```bash
bash scripts/upload_knowledge_base.sh
```

Then trigger RAG ingestion (run rag_ingestion Lambda):
```bash
aws lambda invoke \
    --function-name insuremail-ai-dev-rag-ingestion \
    --payload '{}' \
    /tmp/rag_out.json
cat /tmp/rag_out.json
```

### 2.4 Deploy dashboard

```bash
bash scripts/deploy_dashboard.sh
```

Or manually:
```bash
cd dashboard/frontend
npm install
echo "VITE_API_BASE_URL=$(cd ../../terraform && terraform output -raw api_gateway_url)" > .env
npm run build
aws s3 sync dist/ s3://insuremail-ai-dashboard --delete
aws cloudfront create-invalidation \
    --distribution-id E2ADYLCS9LNMWF \
    --paths "/index.html"
```

### 2.5 Verify

```bash
bash scripts/test_pipeline.sh
```

---

## 3. Incremental Lambda Deploy

Use `scripts/deploy_lambdas.sh` to deploy one or all Lambda functions without
running a full `terraform apply`.

### Deploy a single function

```bash
bash scripts/deploy_lambdas.sh --fn api_handlers
bash scripts/deploy_lambdas.sh --fn classify_intent
bash scripts/deploy_lambdas.sh --fn claude_response
bash scripts/deploy_lambdas.sh --fn email_parser
bash scripts/deploy_lambdas.sh --fn email_sender
bash scripts/deploy_lambdas.sh --fn rag_ingestion
bash scripts/deploy_lambdas.sh --fn rag_retrieval
```

### Deploy all functions at once

```bash
bash scripts/deploy_lambdas.sh --all
```

### Deploy Lambda + Step Functions + dashboard in one shot

```bash
bash scripts/deploy_lambdas.sh --full
```

### What the script does

For each Lambda it:
1. Zips `lambda/<fn>/lambda_function.py` into `/tmp/<fn>.zip`
2. Calls `aws lambda update-function-code`
3. Waits for the update to complete (`aws lambda wait function-updated`)
4. Prints the new code SHA256 as confirmation

### Source directory → deployed function name

| Short name | Deployed function name |
|-----------|----------------------|
| `api_handlers` | `insuremail-ai-dev-api-handlers` |
| `classify_intent` | `insuremail-ai-dev-multi-llm-inference` |
| `claude_response` | `insuremail-ai-dev-claude-response` |
| `email_parser` | `insuremail-ai-dev-email-parser` |
| `email_sender` | `insuremail-ai-dev-email-sender` |
| `rag_ingestion` | `insuremail-ai-dev-rag-ingestion` |
| `rag_retrieval` | `insuremail-ai-dev-rag-retrieval` |

---

## 4. Frontend Deploy

### Quick update (most common)

```bash
cd dashboard/frontend
npm run build
aws s3 sync dist/ s3://insuremail-ai-dashboard --delete
aws cloudfront create-invalidation \
    --distribution-id E2ADYLCS9LNMWF \
    --paths "/index.html"
```

> Only `index.html` needs CloudFront invalidation. All JS/CSS assets are
> content-hashed by Vite and cache-bust automatically on each build.

### Via deploy script

```bash
bash scripts/deploy_lambdas.sh --dashboard
```

### Local development server

```bash
cd dashboard/frontend
npm run dev     # http://localhost:5173
```

Set `.env`:
```
VITE_API_BASE_URL=https://5zzlquytz2.execute-api.us-east-1.amazonaws.com/dev
```

---

## 5. Step Functions Deploy

Update the state machine definition after editing
`step-functions/email_processing_workflow.json`:

```bash
bash scripts/deploy_lambdas.sh --step-functions
```

Or manually:
```bash
STATE_MACHINE_ARN=$(aws stepfunctions list-state-machines \
    --query "stateMachines[?name=='insuremail-ai-dev-email-processor'].stateMachineArn" \
    --output text)

aws stepfunctions update-state-machine \
    --state-machine-arn "$STATE_MACHINE_ARN" \
    --definition file://step-functions/email_processing_workflow.json
```

---

## 6. Knowledge Base Upload

Place source documents (PDF, TXT) in a local folder, then:

```bash
bash scripts/upload_knowledge_base.sh
```

After upload, re-run ingestion:
```bash
aws lambda invoke \
    --function-name insuremail-ai-dev-rag-ingestion \
    --payload '{}' \
    /tmp/rag_out.json && cat /tmp/rag_out.json
```

Check chunk count via the dashboard → RAG Knowledge Base page, or:
```bash
aws dynamodb scan \
    --table-name insuremail-ai-dev-embeddings \
    --select COUNT \
    --query 'Count'
```

---

## 7. Verify Deployment

### Smoke test the pipeline

```bash
bash scripts/test_pipeline.sh
```

### Manual API check

```bash
API=https://5zzlquytz2.execute-api.us-east-1.amazonaws.com/dev

# Dashboard overview
curl -s "$API/api/dashboard/overview" | python3 -m json.tool

# List emails
curl -s "$API/api/emails" | python3 -m json.tool

# Model metrics
curl -s "$API/api/metrics/models" | python3 -m json.tool

# RAG metrics
curl -s "$API/api/metrics/rag" | python3 -m json.tool
```

### Trigger a test email through the pipeline

```bash
aws stepfunctions start-execution \
    --state-machine-arn arn:aws:states:us-east-1:970850578809:stateMachine:insuremail-ai-dev-email-processing \
    --input '{
        "email_id": "test-001",
        "s3_bucket": "insuremail-ai-dev-emails",
        "s3_key": "test/sample.eml"
    }'
```

### Check Lambda logs

```bash
# Most recent log stream for any function
aws logs tail /aws/lambda/insuremail-ai-dev-api-handlers --follow
aws logs tail /aws/lambda/insuremail-ai-dev-multi-llm-inference --follow
aws logs tail /aws/lambda/insuremail-ai-dev-claude-response --follow
```

---

## 8. Environment Reference

### AWS resources (dev)

| Resource | Name / ARN |
|----------|-----------|
| API Gateway URL | `https://5zzlquytz2.execute-api.us-east-1.amazonaws.com/dev` |
| Dashboard S3 | `insuremail-ai-dashboard` |
| CloudFront distribution | `E2ADYLCS9LNMWF` |
| Email S3 bucket | `insuremail-ai-dev-emails` |
| Knowledge base S3 | `insuremail-ai-dev-knowledge-base` |
| Email DynamoDB table | `insuremail-ai-dev-email-processing` |
| Model metrics table | `insuremail-ai-dev-model-metrics` |
| Embeddings table | `insuremail-ai-dev-embeddings` |
| Step Functions | `insuremail-ai-dev-email-processing` |
| Lambda exec role | `insuremail-ai-dev-lambda-execution` |
| Region | `us-east-1` |

### Lambda environment variables

| Variable | Set on | Example value |
|----------|--------|---------------|
| `EMAIL_TABLE_NAME` | all Lambdas | `insuremail-ai-dev-email-processing` |
| `MODEL_METRICS_TABLE_NAME` | classify_intent, claude_response, api_handlers | `insuremail-ai-dev-model-metrics` |
| `EMBEDDINGS_TABLE_NAME` | rag_ingestion, rag_retrieval, api_handlers | `insuremail-ai-dev-embeddings` |
| `KNOWLEDGE_BASE_BUCKET` | rag_ingestion | `insuremail-ai-dev-knowledge-base` |
| `EMAIL_BUCKET_NAME` | email_parser, email_sender | `insuremail-ai-dev-emails` |
| `SES_SENDER_EMAIL` | email_sender | `noreply@yourdomain.com` |
| `PRIMARY_MODEL_ID` | claude_response | `anthropic.claude-3-sonnet-20240229-v1:0` |
| `ACTIVE_MODEL` | classify_intent, claude_response | `mistral-7b` |
| `CLASSIFY_INTENT_FUNCTION_NAME` | api_handlers | `insuremail-ai-dev-multi-llm-inference` |
| `CLAUDE_RESPONSE_FUNCTION_NAME` | api_handlers | `insuremail-ai-dev-claude-response` |
| `EMAIL_SENDER_FUNCTION_NAME` | api_handlers | `insuremail-ai-dev-email-sender` |

---

## 9. Rollback

### Roll back a Lambda to the previous version

```bash
# Get previous code SHA256 from CloudWatch logs or git history, then re-zip and redeploy
bash scripts/deploy_lambdas.sh --fn <name>

# Or use Lambda aliases / versions (if configured)
aws lambda update-alias \
    --function-name insuremail-ai-dev-multi-llm-inference \
    --name live \
    --function-version <previous-version-number>
```

### Roll back infrastructure

```bash
cd terraform
git checkout <previous-commit> -- .
terraform apply
```

### Roll back dashboard

```bash
cd dashboard/frontend
git checkout <previous-commit> -- src/
npm run build
aws s3 sync dist/ s3://insuremail-ai-dashboard --delete
aws cloudfront create-invalidation \
    --distribution-id E2ADYLCS9LNMWF \
    --paths "/index.html"
```
