# Deployment Status - InsureMail AI

**Last Updated**: 2026-03-04
**Status**: ✅ **FULLY OPERATIONAL WITH EVALUATION METRICS INTEGRATED**

---

## ✅ **LATEST UPDATE: Evaluation Metrics Integration Complete**

### What Was Done

The `evaluation_metrics` Lambda function is now **fully integrated** into the system:

#### 1. **Automated Scheduled Execution** ✅
- **Daily metrics** (9:00 AM UTC): Calculates last 7 days of performance
- **Weekly reports** (Sunday 00:00 UTC): Comprehensive 30-day analysis
- Powered by AWS EventBridge (CloudWatch Events)

#### 2. **API Integration** ✅
- API endpoint `/api/metrics/models` now calls evaluation_metrics Lambda
- Dashboard can query model performance on-demand
- Fallback to direct DynamoDB queries if Lambda unavailable

#### 3. **IAM Permissions** ✅
- Added `lambda:InvokeFunction` permission for api_handlers
- EventBridge has permission to trigger evaluation_metrics
- All IAM policies properly configured

#### 4. **Environment Configuration** ✅
- api_handlers Lambda has `EVALUATION_METRICS_FUNCTION_NAME` env var
- Proper Lambda-to-Lambda invocation setup

---

## Recent Fixes Completed

### 1. ✅ RAG Embedding Storage Bug (CRITICAL)
**Issue**: `'decimal.Context' object has no attribute 'create_type_serializer'`
- **Root Cause**: DynamoDB cannot serialize Python float lists directly
- **Fix**: Convert embeddings to JSON strings before storage
- **Files Modified**:
  - `lambda/rag_ingestion/lambda_function.py` - Added `json.dumps(embedding)`
  - `lambda/rag_retrieval/lambda_function.py` - Added `json.loads()` for parsing
- **Status**: ✅ Tested and working

### 2. ✅ Model Configuration Issues
**Issues**:
- Llama 3.1 8B required inference profile
- Titan Express reached EOL (end of life)
- CLAUDE_MODEL_ID variable undefined

**Fixes**:
- Changed to inference profile: `us.meta.llama3-1-8b-instruct-v1:0`
- Removed deprecated `amazon.titan-text-express-v1`
- Fixed variable reference: `CLAUDE_MODEL_ID` → `PRIMARY_MODEL_ID`

**Files Modified**:
- `lambda/claude_response/lambda_function.py` (line 113 + model configs)
- `lambda/multi_llm_inference/lambda_function.py` (model list)
- `terraform/variables.tf` (bedrock_models list)

**Status**: ✅ Deployed and tested

### 3. ✅ S3 Event Triggers for RAG
**Issue**: Knowledge base documents not automatically processed
- **Fix**: Added S3 bucket notifications to trigger `rag_ingestion` Lambda
- **Files Modified**: `terraform/modules/storage/main.tf`
- **Status**: ✅ Working - documents auto-process on upload

### 4. ✅ Evaluation Metrics Integration (NEW)
**Issue**: evaluation_metrics Lambda was deployed but never used
- **Fix**: Full integration with EventBridge, API handlers, and IAM
- **Files Created**:
  - `terraform/modules/monitoring/eventbridge.tf`
  - `docs/EVALUATION_METRICS_INTEGRATION.md`
- **Files Modified**:
  - `terraform/main.tf` (added evaluation_metrics_lambda_arn to monitoring module)
  - `terraform/modules/monitoring/variables.tf` (new variable)
  - `terraform/modules/lambda/main.tf` (env var for api_handlers)
  - `terraform/modules/iam/main.tf` (Lambda invoke permission)
  - `lambda/api_handlers/lambda_function.py` (calls evaluation_metrics Lambda)
- **Status**: ✅ Deployed and tested

---

## Current Configuration

### Active Models (100% Open Source)
| Model | Purpose | Cost per 1M tokens | Status |
|-------|---------|---------------------|--------|
| **Mistral 7B** | Primary response generation | $0.15/$0.20 | ✅ Working |
| **Llama 3.1 8B** | Fallback model | $0.30/$0.60 | ✅ Working |
| **Titan Embeddings** | RAG/semantic search | $0.10 | ✅ Working |

### System Architecture
```
Email (SES)
  → SNS Topic
    → Email Receiver Lambda
      → Step Functions
        ├─ Email Parsing
        ├─ Intent Classification (Multi-LLM)
        ├─ Entity Extraction (Multi-LLM)
        ├─ RAG Retrieval (Titan Embeddings)
        ├─ CRM Validation
        ├─ Fraud Scoring
        └─ Response Generation (Mistral/Llama)
          → Auto-Send or Human Review

Evaluation Metrics Lambda (Separate Flow):
  ← EventBridge Schedule (Daily 9am, Weekly Sunday)
  ← API Handlers (Dashboard queries)
  ← Manual Invocation (CLI/testing)
  → Queries MODEL_METRICS_TABLE
  → Returns aggregated statistics
```

### Cost Estimate
- **1,000 emails/day**: ~$13-18/month
- **Primary savings**: Switched from Claude ($21/month) to Mistral 7B
- **Free tier coverage**: Lambda, DynamoDB, S3 largely covered

---

## Deployment Status

### All Lambda Functions Deployed ✅
```
✅ insuremail-ai-dev-email-receiver
✅ insuremail-ai-dev-email-sender
✅ insuremail-ai-dev-email-parser
✅ insuremail-ai-dev-multi-llm-inference
✅ insuremail-ai-dev-claude-response
✅ insuremail-ai-dev-rag-ingestion
✅ insuremail-ai-dev-rag-retrieval
✅ insuremail-ai-dev-evaluation-metrics
✅ insuremail-ai-dev-api-handlers
```

### EventBridge Rules ✅
```
✅ insuremail-ai-dev-daily-metrics (cron: 0 9 * * ? *) - ENABLED
✅ insuremail-ai-dev-weekly-report (cron: 0 0 ? * SUN *) - ENABLED
```

### IAM Permissions ✅
```
✅ lambda:InvokeFunction (api_handlers → evaluation_metrics)
✅ events.amazonaws.com → evaluation_metrics Lambda
✅ Bedrock model access
✅ DynamoDB read/write
✅ S3 read/write
✅ SES send email
```

---

## Testing the System

### 1. Test RAG Ingestion
```bash
# Upload a knowledge base document
aws s3 cp docs/sample_policy.txt s3://insuremail-ai-dev-knowledge-base/policies/

# Check CloudWatch logs
aws logs tail /aws/lambda/insuremail-ai-dev-rag-ingestion --follow
```

### 2. Test Email Processing
```bash
# Send test email to your verified SES address
# Or use the test script:
python scripts/test_email_workflow.py
```

### 3. Test Evaluation Metrics
```bash
# Direct invocation
aws lambda invoke \
  --function-name insuremail-ai-dev-evaluation-metrics \
  --cli-binary-format raw-in-base64-out \
  --payload file://<(echo '{"task_type":"all","days":7}') \
  output.json

# View results
cat output.json | jq '.statistics'
```

### 4. Test API Endpoint
```bash
# Get model metrics via API
curl "https://5zzlquytz2.execute-api.us-east-1.amazonaws.com/dev/api/metrics/models?days=7"
```

---

## Known Working Test Results

### Last Test Execution (from user)
- ✅ Email received and parsed
- ✅ Intent classification: "claim_inquiry"
- ✅ Entity extraction: Worked
- ✅ RAG retrieval: 3 relevant docs found
- ✅ Mistral 7B: Generated response successfully
- ✅ Confidence score: 0.85 (auto-response threshold)

### Evaluation Metrics Test
- ✅ Lambda invoked successfully
- ✅ Returns proper JSON structure
- ✅ EventBridge rules created and enabled
- ✅ API handler has proper environment variable

---

## ⚠️ SES Sandbox Mode Issue

**Current Issue**: Amazon SES is in **sandbox mode**

**Impact**: Can only send emails **TO** verified addresses

**Error Message**:
```
Email address is not verified. The following identities failed the check in region US-EAST-1: yil***@gmail.com
```

**Quick Fix**:
```bash
# Verify recipient email address
aws ses verify-email-identity --email-address YOUR_RECIPIENT_EMAIL@gmail.com

# Check inbox for verification email from: no-reply-aws@amazon.com
# Click verification link

# Check status
aws ses get-identity-verification-attributes --identities YOUR_EMAIL@gmail.com
```

**Long-term Solution**: Request SES Production Access
- See: `/docs/SES_SETUP.md` for detailed instructions
- Typically approved within 24-48 hours
- Removes recipient verification requirement
- Increases sending limits to 50,000 emails/day

---

## Deployment Commands

### Full Deployment
```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### Lambda Only
```bash
cd terraform
terraform apply -target=module.lambda
```

### Monitoring/EventBridge Only
```bash
cd terraform
terraform apply -target=module.monitoring
```

### Verify Deployment
```bash
# Check all resources
terraform state list | wc -l

# Get key outputs
terraform output lambda_functions
terraform output step_functions_arn

# Check EventBridge rules
aws events list-rules --name-prefix "insuremail-ai-dev"

# Test evaluation metrics
aws lambda invoke \
  --function-name insuremail-ai-dev-evaluation-metrics \
  --cli-binary-format raw-in-base64-out \
  --payload file://<(echo '{"task_type":"all","days":7}') \
  output.json
```

---

## Documentation

### Complete Guides
- ✅ `/docs/EVALUATION_METRICS_INTEGRATION.md` - Full integration guide (NEW)
- ✅ `/docs/SES_SETUP.md` - Email setup and verification
- ✅ `/docs/OPEN_SOURCE_MODELS.md` - Model comparison and costs
- ✅ `/docs/COST_OPTIMIZATION.md` - Detailed cost breakdown
- ✅ `/docs/RAG_SETUP.md` - Knowledge base configuration
- ✅ `/docs/DEPLOYMENT_STATUS.md` - This file

### Setup Scripts
- ✅ `/scripts/setup_ses.sh` - Interactive SES verification
- ✅ `/scripts/upload_knowledge_base.sh` - Knowledge base management
- ✅ `/scripts/request_production_access.sh` - SES production access helper

---

## Troubleshooting

### If RAG retrieval returns no documents:
```bash
# Check if embeddings exist
aws dynamodb scan --table-name insuremail-ai-dev-embeddings --max-items 1

# Re-upload knowledge base
./scripts/upload_knowledge_base.sh
```

### If Lambda functions timeout:
- Check CloudWatch logs for specific errors
- Verify IAM permissions for Bedrock access
- Ensure models are enabled in your AWS region

### If emails not triggering workflow:
- Verify SES receipt rule is active
- Check SNS topic subscription
- Review email receiver Lambda logs

### If evaluation metrics not running:
```bash
# Check EventBridge rule
aws events describe-rule --name insuremail-ai-dev-daily-metrics

# Check Lambda permissions
aws lambda get-policy --function-name insuremail-ai-dev-evaluation-metrics

# Manual test
aws lambda invoke \
  --function-name insuremail-ai-dev-evaluation-metrics \
  --cli-binary-format raw-in-base64-out \
  --payload file://<(echo '{"task_type":"all","days":7}') \
  output.json
```

---

## Next Steps (Optional Enhancements)

1. **Resolve SES Sandbox** ⚠️ **PRIORITY**
   - Request production access via AWS Console
   - Remove recipient verification requirement
   - See `/scripts/request_production_access.sh`

2. **Production Deployment**
   - Change environment from "dev" to "prod"
   - Enable CloudWatch alarms
   - Set up backup/disaster recovery

3. **Dashboard Setup**
   - Deploy React frontend (already built)
   - Configure Cognito auth
   - Set up CloudFront distribution

4. **Advanced Features**
   - Add sentiment analysis
   - Implement A/B testing for model selection
   - Build feedback loop for model improvement

5. **Monitoring**
   - Create custom CloudWatch dashboard
   - Set up cost alerts
   - Configure PagerDuty/SNS for critical errors

---

## Support

- **Documentation**: See `/docs` folder for detailed guides
- **Logs**: CloudWatch Logs - Filter by `/aws/lambda/insuremail-ai-dev-*`
- **State**: Terraform state in S3 backend
- **Issues**: Check AWS console for resource-specific errors
- **EventBridge**: Check `/aws/events/rules/insuremail-ai-dev-*` for scheduled tasks

---

**System Status**: ✅ All components operational and tested
**Cost Optimization**: ✅ Using 100% open-source models
**Bug Fixes**: ✅ All critical bugs resolved
**Evaluation Metrics**: ✅ Fully integrated with automated scheduling
**Ready for**: Production deployment (after SES production access)

**Known Issue**: SES in sandbox mode - recipient emails must be verified
**Action Required**: Verify recipient emails OR request SES production access
