# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**InsureMail AI** — AWS serverless email classification and auto-response system for insurance companies. Uses AWS Bedrock (Mistral 7B for intent classification and response generation, Llama 3.1 8B as fallback, Titan Embeddings V2 for RAG), Step Functions orchestration, and a React dashboard.

## Environment Setup

### AWS Credentials & Region
```bash
export AWS_PROFILE=your-profile  # or set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY
export AWS_REGION=us-east-1      # required by Terraform
aws sts get-caller-identity       # verify credentials
```

### Bedrock Model Access
Enable in AWS Console → Bedrock → Model access (one-time):
- `amazon.titan-embed-text-v2:0` (Embeddings)
- `mistral.mistral-7b-instruct-v0:2` (Intent/Response)
- `meta.llama3-8b-instruct-v1:0` (Fallback)

### Local Development
```bash
# Set required env var for tests
export EMAIL_TABLE_NAME=test-emails

# Dashboard API endpoint (from terraform output)
export VITE_API_BASE_URL=https://your-api-id.execute-api.us-east-1.amazonaws.com/dev
```

## Commands

### Testing
```bash
# Required env var for unit tests that import lambda modules at collection time:
EMAIL_TABLE_NAME=test-emails pytest tests/unit/

# Run a single test file:
EMAIL_TABLE_NAME=test-emails pytest tests/unit/test_email_parser.py -v

# Run a single test by name:
EMAIL_TABLE_NAME=test-emails pytest tests/unit/test_email_parser.py::TestAttachmentCounting::test_attachment_detected_in_multipart

# Skip slow tests:
pytest tests/ -m "not slow" -v

# All tests via Makefile (sets env vars via scripts/run_tests.sh):
make test
make test-unit
make test-coverage   # generates htmlcov/index.html
```

### Linting & Formatting
```bash
make lint        # flake8, line length 120
make fmt         # black --line-length 120
make pre-commit  # fmt + lint + test
```

### Terraform
```bash
make tf-init      # terraform init
make tf-plan      # show planned changes
make tf-apply     # deploy (prompts for confirmation)
make deploy-lambda  # redeploy Lambda functions only
```

### Dashboard (React + Vite)
```bash
cd dashboard/frontend

# Development
npm install
npm run dev      # http://localhost:3000 (HMR enabled)

# Production build
npm run build    # outputs to dist/

# Deploy to S3
make dashboard-deploy   # builds, syncs dist/ to S3, invalidates CloudFront (if configured)
```

Set `VITE_API_BASE_URL` in `dashboard/frontend/.env`:
```
VITE_API_BASE_URL=https://your-api-id.execute-api.us-east-1.amazonaws.com/dev
```

Note: Frontend S3 bucket (`insuremail-ai-{env}-frontend`) is auto-created by Terraform. Website endpoint is available in `terraform output frontend_bucket_website_endpoint`.

### Data Loading & Assessment Scripts
```bash
python scripts/load_customers.py         # bulk-load customers.jsonl → DynamoDB (idempotent)
python scripts/load_knowledge_docs.py    # Titan-embed knowledge docs → DynamoDB
python scripts/run_stepfn_assessment.py  # live pipeline eval against Laya dataset (20–1000 emails)
python scripts/StepFunctionAssignment.py # demo: upload MIME emails to S3, trigger live Step Functions
```

## Architecture

### Pipeline (Step Functions)

`step-functions/email_processing_workflow.json` defines the 6-step workflow:

```
email_parser
    ↓
[ClassifyIntent ∥ ExtractEntities]   ← parallel; FallbackEntities on error
    ↓
rag_retrieval                         ← SetEmptyRAG fallback on error
    ↓
crm_validation                        ← SetEmptyCRM fallback on error
    ↓
claude_response
    ↓
email_sender  → auto_response (≥0.8) / human_review (0.5–0.8) / escalate (<0.5)
```

Graceful fallbacks mean the pipeline never hard-fails mid-run. All errors result in escalation at `email_sender`.

### Lambda Functions (`lambda/`)

| Function | Role |
|---|---|
| `email_parser` | RFC 2822 parse, PII redact, PDF/DOCX/TXT extraction, `_dynamo_safe()` float→Decimal |
| `classify_intent_by_llm` | Mistral 7B → 17 intents → 12 route teams via `INTENT_TO_ROUTE` map |
| `classify_intent_by_biobert` | BioBERT fallback (alternative to LLM classifier) |
| `extract_entity` | Bedrock Claude for structured field extraction from emails + attachments |
| `rag_retrieval` | HyDE (Haiku) + Titan vector + BM25 + RRF fusion + cross-encoder rerank |
| `crm_validation` | Text-to-SQL (Mistral 7B) → DynamoDB customer/policy lookup |
| `claude_response` | Mistral/Llama response generation + 8-dimension quality judge |
| `email_sender` | Confidence-based routing (auto ≥0.8, review 0.5-0.8, escalate <0.5) + SES |
| `rag_ingestion` | 500-token chunks, 50-token overlap, MD5 dedup → Titan embed → DynamoDB |
| `api_handlers` | REST API for dashboard (list emails, detail, update response, metrics) |
| `save_result` | Persist pipeline execution results to DynamoDB |
| `gmail_imap_poller` | Scheduled Gmail IMAP polling (alternative to SES) |
| `sagemaker_inference` | PyTorch GPU inference endpoint integration |

### Terraform Modules (`terraform/modules/`)

| Module | Purpose |
|---|---|
| `storage` | S3 buckets (emails, knowledge-base, logs, frontend), DynamoDB tables |
| `lambda` | All 13 Lambda functions + CloudWatch logs + layers |
| `step-functions` | Email processing workflow orchestration |
| `api-gateway` | REST API routes, CORS, Lambda integration |
| `iam` | Execution roles, policies, cross-service permissions |
| `bedrock` | Model access configuration (no resources, placeholder) |
| `ses` | Email sending identity, bounce/complaint handling |
| `monitoring` | CloudWatch alarms, dashboards, EventBridge rules |
| `sagemaker` | GPU inference endpoint for PyTorch model |

All resources tagged `Project=InsureMailAI, ManagedBy=Terraform`. DynamoDB uses `PAY_PER_REQUEST`.

### DynamoDB Tables

| Table | PK | SK/GSI | Purpose |
|---|---|---|---|
| `email_processing` | `email_id` (UUID) | `timestamp-index` (GSI) | Raw email metadata + parsed content |
| `model_metrics` | `metric_key` ({model}#{task}#{email}) | — | Evaluation metrics for each model/task/email |
| `kb_embeddings` | `doc_id` (MD5 hash) | `doc-type-index` (GSI) | Knowledge base chunks + Titan embeddings |
| `customers` | `customer_id` | — | CRM customer/policy data for lookup |
| `pipeline_results` | `email_id` | `action-date-index` (GSI: {action}#{date}) | Final routing decision + execution trace |

## Dashboard REST API Endpoints

Base: `{VITE_API_BASE_URL}/api`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/emails` | List all emails (paginated, filters: status, confidence, intent) |
| `GET` | `/emails/{email_id}` | Single email detail + full trace |
| `POST` | `/emails/{email_id}/response` | Update/approve generated response before sending |
| `GET` | `/metrics/model` | Model accuracy/timing metrics by task |
| `GET` | `/metrics/rag` | Knowledge base stats (chunks, embeddings) |
| `GET` | `/metrics/eval` | Bedrock evaluation job results |
| `POST` | `/model/inference` | Test model on custom email (SageMaker endpoint) |

## Debugging & Common Issues

### Tests fail with `ModuleNotFoundError: No module named 'lambda_function'`
Tests must clean up module cache before importing Lambda handlers:
```python
sys.modules.pop('lambda_function', None)
from lambda.email_parser import lambda_function
```
See `tests/conftest.py` for shared fixtures.

### DynamoDB Decimal types in tests
Moto returns `Decimal` instead of `float`. Convert explicitly:
```python
assert int(result['confidence_score']) == 85  # not == 0.85
```

### Step Functions state machine stuck in RUNNING
Check CloudWatch logs for specific Lambda failure. Use `aws stepfunctions describe-execution` to inspect input/output at each step.

### Frontend build warnings (chunk size > 500 kB)
Non-critical. Use dynamic imports (`React.lazy()`) if code-splitting is needed. Vite build succeeds regardless.

### API Gateway CORS errors in browser
Ensure `VITE_API_BASE_URL` is set correctly in `dashboard/frontend/.env` and matches Terraform API Gateway output. OPTIONS preflight requires CORS headers from Lambda (configured in `api-gateway` module).

## Key Conventions

### Bedrock Model IDs
- Mistral 7B (intent, entity extraction, HyDE, rerank, response gen, CRM SQL): `mistral.mistral-7b-instruct-v0:2`
- Llama 3.1 8B (fallback, response gen): `meta.llama3-8b-instruct-v1:0`
- Titan Embeddings V2 (1024-dim): `amazon.titan-embed-text-v2:0`

### Model Selection
Dashboard allows switching between Mistral 7B and Llama 3.1 8B at runtime:
- **Mistral 7B** (default): Optimized for intent classification + response generation, faster, lower cost
- **Llama 3.1 8B** (fallback): Larger context, more nuanced responses, higher latency

Switch in Dashboard UI → Settings or via environment variable in `claude_response` Lambda:
```python
MODEL_ID = os.getenv('LLM_MODEL_ID', 'mistral.mistral-7b-instruct-v0:2')
```

### Test Patterns
- **AWS mocking**: `@mock_aws` from moto v5.x — never `@mock_dynamodb` or `@mock_s3`.
- **Module collision**: Each test file calls `sys.modules.pop('lambda_function', None)` before importing its Lambda module.
- **DynamoDB Decimal**: moto returns `Decimal` types; use `int(item['field'])` in assertions.
- **`lambda_context`**: tests that call `lambda_handler` need a `lambda_context` pytest fixture (typically `MagicMock()`).

### 17 Valid Intent Classes
`coverage_query`, `claim_submission`, `claim_status`, `claim_reimbursement_query`, `pre_authorisation`, `payment_issue`, `policy_change`, `renewal_query`, `cancellation_request`, `enrollment_new_policy`, `dependent_addition`, `complaint`, `document_followup`, `hospital_network_query`, `id_verification`, `broker_query`, `other`

### Data Standards
- Timestamps: ISO 8601 UTC (`2026-03-10T09:00:00Z`)
- All AI outputs include `confidence_score` (float 0–1)
- PII redacted in all logs via `email_parser.redact_pii()`
- Attachment text extraction: PDF → `pdf_document`, DOCX → `word_document`, TXT → `text_document`; images skipped (handled by `extract_entity` via Textract)
