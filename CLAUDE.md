# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**InsureMail AI** — AWS serverless email classification and auto-response system for insurance companies. Uses AWS Bedrock (Claude 3 Sonnet for intent classification, Mistral 7B for response generation, Titan V2 for embeddings), Step Functions orchestration, and a React dashboard.

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
npm install
npm run dev      # http://localhost:3000
npm run build    # output to dist/
```
Set `VITE_API_BASE_URL` in `dashboard/frontend/.env` to the API Gateway URL (`terraform output api_gateway_url`).

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
| `classify_intent` | Claude 3 Sonnet → 17 intents → 12 route teams via `INTENT_TO_ROUTE` map |
| `extract_entity` | AWS Textract + Bedrock Claude for structured field extraction from attachments |
| `rag_retrieval` | HyDE (Haiku) + Titan vector + BM25 + RRF fusion + cross-encoder rerank |
| `crm_validation` | Text-to-SQL (Mistral 7B) → DynamoDB customer/policy lookup, no `Limit=` on Scan |
| `claude_response` | Mistral/Llama response gen + 8-dim quality judge |
| `email_sender` | Confidence-based routing + Amazon SES |
| `rag_ingestion` | 500-token chunks, 50-token overlap, MD5 dedup → Titan embed → DynamoDB |
| `api_handlers` | REST API for dashboard; uses FilterExpression on DynamoDB Scan (no GSI) |
| `gmail_imap_poller` | Scheduled Gmail IMAP polling |

### Terraform Modules (`terraform/modules/`)

`iam`, `storage`, `lambda`, `step-functions`, `api-gateway`, `bedrock`, `ses`, `monitoring`.
All resources tagged `Project=InsureMailAI, ManagedBy=Terraform`. DynamoDB uses `PAY_PER_REQUEST`.

### DynamoDB Tables

| Table | PK | SK |
|---|---|---|
| `email_processing` | `email_id` (UUID) | — |
| `model_metrics` | `task_type` | `model_id#timestamp` |
| `kb_embeddings` | `doc_id` | — |
| `customers` | `customer_id` | — |

## Key Conventions

### Bedrock Model IDs
- Claude 3 Sonnet (intent): `anthropic.claude-3-sonnet-20240229-v1:0`
- Claude 3 Haiku (HyDE + rerank): `anthropic.claude-3-haiku-20240307-v1:0`
- Mistral 7B (response gen + CRM SQL): `mistral.mistral-7b-instruct-v0:2`
- Llama 3.1 8B (fallback): `meta.llama3-8b-instruct-v1:0`
- Titan Embeddings V2 (1024-dim): `amazon.titan-embed-text-v1`

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
