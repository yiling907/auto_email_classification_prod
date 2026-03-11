# InsureMail AI — Developer Guide

This document is the primary reference for developers working on the codebase. It covers
project structure, local setup, data schemas, Lambda internals, API reference, deployment
workflow, and known gotchas.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Local Development Setup](#2-local-development-setup)
3. [Lambda Functions](#3-lambda-functions)
4. [Step Functions Workflow](#4-step-functions-workflow)
5. [DynamoDB Table Schemas](#5-dynamodb-table-schemas)
6. [API Reference](#6-api-reference)
7. [Frontend Development](#7-frontend-development)
8. [Evaluation Pipeline](#8-evaluation-pipeline)
9. [Deployment Cheatsheet](#9-deployment-cheatsheet)
10. [Testing](#10-testing)
11. [Known Pitfalls](#11-known-pitfalls)

---

## 1. Project Structure

```
auto_email_classification_prod/
├── CLAUDE.md                     # Claude Code development guidance
├── DEVELOPMENT.md                # This file
├── README.md                     # Project overview and quick start
├── Makefile                      # Common dev commands (see §9)
├── pytest.ini                    # Pytest config (coverage thresholds)
│
├── lambda/                       # All Lambda function source code
│   ├── api_handlers/             # Dashboard REST API
│   ├── classify_intent/          # Multi-LLM intent classification
│   ├── claude_response/          # Claude 3 response generation
│   ├── email_parser/             # Email body parsing + entity extraction
│   ├── email_sender/             # SES outbound email sender
│   ├── gmail_imap_poller/        # Gmail IMAP polling (alternative to SES)
│   ├── rag_ingestion/            # Knowledge base document ingestion
│   └── rag_retrieval/            # Semantic search against knowledge base
│
├── step-functions/
│   └── email_processing_workflow.json   # Step Functions state machine definition
│
├── terraform/                    # Infrastructure as Code
│   ├── main.tf                   # Root module (calls sub-modules)
│   ├── variables.tf              # Input variables
│   ├── outputs.tf                # Output values (API URL, bucket names, …)
│   ├── terraform.tfvars          # Actual variable values (gitignored in prod)
│   ├── terraform.tfvars.example  # Template for tfvars
│   └── modules/
│       ├── lambda/               # Lambda function resources
│       ├── storage/              # S3 buckets
│       ├── database/             # DynamoDB tables
│       ├── api_gateway/          # API Gateway REST API
│       ├── step_functions/       # Step Functions state machine
│       ├── iam/                  # IAM roles and policies
│       ├── monitoring/           # CloudWatch alarms and dashboards
│       └── ses/                  # SES email identity
│
├── dashboard/
│   ├── README.md                 # Dashboard-specific setup guide
│   └── frontend/
│       ├── src/
│       │   ├── App.jsx           # Routes + nav
│       │   ├── App.css           # Global styles
│       │   └── pages/
│       │       ├── Dashboard.jsx      # Overview + model settings
│       │       ├── EmailsList.jsx     # Email list with filters
│       │       ├── EmailDetail.jsx    # Single email + editable response
│       │       ├── ModelMetrics.jsx   # 4-tab model performance page
│       │       ├── RAGMetrics.jsx     # Knowledge base stats
│       │       └── Evaluations.jsx    # Bedrock evaluation results
│       ├── vite.config.js
│       └── package.json
│
├── scripts/                      # Utility and evaluation scripts
│   ├── generate_eval_datasets.py # Builds JSONL eval datasets from laya data
│   ├── run_local_evaluation.py   # Local eval: intent/routing/entity extraction
│   ├── run_full_evaluation.py    # Orchestrator: generate → eval → Bedrock jobs
│   ├── deploy_dashboard.sh       # Build + S3 sync + CloudFront invalidation
│   ├── run_tests.sh              # Test runner
│   └── upload_knowledge_base.sh  # Upload PDFs to S3 for RAG ingestion
│
├── tests/
│   ├── conftest.py               # Shared fixtures (env vars, moto tables)
│   ├── requirements.txt          # Test dependencies
│   ├── unit/                     # Per-Lambda unit tests (moto)
│   ├── integration/              # End-to-end workflow tests
│   ├── terraform/                # Terraform validation tests
│   └── test_data/
│       └── laya_synthetic_dataset_starter/
│           ├── DATA_SCHEMA.md
│           ├── emails.jsonl          # 1000 emails with gold labels
│           ├── cases.jsonl           # 1000 cases linked to emails
│           ├── draft_responses.jsonl # 1000 generated replies (reference)
│           └── attachment_content.jsonl  # 1044 attachment records
│
└── results/                      # Eval report output (gitignored)
    └── eval_report_<timestamp>.json
```

---

## 2. Local Development Setup

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | >= 3.11 | `brew install python` |
| Node.js | >= 18 | `brew install node` |
| Terraform | >= 1.0 | `brew install terraform` |
| AWS CLI | v2 | `brew install awscli` |

### Python environment

```bash
cd /path/to/auto_email_classification_prod

# Create and activate virtualenv
python3 -m venv venv
source venv/bin/activate

# Install test + dev dependencies
pip install -r tests/requirements.txt
```

### AWS credentials

```bash
export AWS_PROFILE=your-profile      # or use AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
export AWS_REGION=us-east-1
```

Verify access:
```bash
aws sts get-caller-identity
aws bedrock list-foundation-models --query 'modelSummaries[?contains(modelId,`claude`)].modelId'
```

### Frontend

```bash
cd dashboard/frontend
npm install
cp .env.example .env          # if it exists, else create manually
echo "VITE_API_BASE_URL=$(cd ../../terraform && terraform output -raw api_gateway_url)" >> .env
npm run dev                   # http://localhost:5173
```

---

## 3. Lambda Functions

All Lambdas are Python 3.11, use structured JSON logging, and return HTTP-style
`{statusCode, body}` dicts. Every function has `lambda_function.py` as its entry point.

### 3.1 `classify_intent` (deployed as `insuremail-ai-dev-multi-llm-inference`)

**Purpose**: Classify an email into one of 17 intents, derive routing team and priority,
compute a confidence score.

**Trigger**: Step Functions (invoked by the state machine's ClassifyIntent parallel branch)

**Input event**:
```json
{
  "email_id": "uuid",
  "parsed_email": {
    "subject": "...",
    "body_text": "...",
    "sender_email": "...",
    "detected_language": "en"
  }
}
```

**Output** (in `body` as JSON):
```json
{
  "customer_intent": "coverage_query",
  "confidence": 0.92,
  "route_team": "customer_support_team",
  "priority": "medium",
  "urgency": "normal",
  "sentiment": "neutral",
  "requires_human_review": false,
  "action": "auto_response"
}
```

**Key env vars**:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MODEL_METRICS_TABLE_NAME` | — | DynamoDB table for metrics |
| `ACTIVE_MODEL` | `mistral-7b` | Active inference model (`mistral-7b` or `llama-3.1-8b`) |

**Valid intents** (17): `coverage_query`, `claim_submission`, `claim_status`,
`claim_reimbursement_query`, `pre_authorisation`, `payment_issue`, `policy_change`,
`renewal_query`, `cancellation_request`, `enrollment_new_policy`, `dependent_addition`,
`complaint`, `document_followup`, `hospital_network_query`, `id_verification`,
`broker_query`, `other`

**Model IDs used**:
- `mistral-7b` → `mistral.mistral-7b-instruct-v0:2`
- `llama-3.1-8b` → `meta.llama3-8b-instruct-v1:0`

---

### 3.2 `claude_response` (deployed as `insuremail-ai-dev-claude-response`)

**Purpose**: Generate a customer-facing email reply using Claude 3 Sonnet with RAG context.

**Trigger**: Step Functions (GenerateResponse state)

**Input event**:
```json
{
  "email_id": "uuid",
  "parsed_email": { "body_text": "...", "sender_email": "..." },
  "classification": {
    "customer_intent": "coverage_query",
    "confidence": 0.92,
    "route_team": "customer_support_team"
  },
  "rag_results": {
    "retrieved_documents": [
      { "doc_id": "doc_001", "content": "...", "similarity_score": 0.87 }
    ]
  }
}
```

**Output**:
```json
{
  "email_id": "uuid",
  "llm_response": "Dear Customer, ...",
  "model_used": "anthropic.claude-3-sonnet-20240229-v1:0",
  "tokens_used": 512,
  "reference_ids": ["doc_001"]
}
```

**Key env vars**:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PRIMARY_MODEL_ID` | `anthropic.claude-3-sonnet-20240229-v1:0` | Primary Bedrock model |
| `ACTIVE_MODEL` | `mistral-7b` | Fallback model selector |
| `MODEL_METRICS_TABLE_NAME` | — | Metrics storage |

**Confidence → action mapping**:

| Confidence | Action |
|-----------|--------|
| ≥ 0.8 | `auto_response` |
| 0.5 – 0.8 | `human_review` |
| < 0.5 | `escalate` |

---

### 3.3 `email_parser` (deployed as `insuremail-ai-dev-email-parser`)

**Purpose**: Parse a raw email (S3 object), extract entities (policy number, member ID, PII),
detect language, and write the structured record to DynamoDB.

**Trigger**: S3 event (new object in raw email bucket)

**Key env vars**: `EMAIL_TABLE_NAME`, `EMAIL_BUCKET_NAME`

---

### 3.4 `rag_ingestion` (deployed as `insuremail-ai-dev-rag-ingestion`)

**Purpose**: Read PDFs/text from S3, chunk them (500 tokens, 50-token overlap), embed
with Amazon Titan, store vectors in DynamoDB.

**Chunking**: 500 tokens per chunk, 50 overlap
**Embedding model**: `amazon.titan-embed-text-v1` (1536 dimensions)
**Key env vars**: `EMBEDDINGS_TABLE_NAME`, `KNOWLEDGE_BASE_BUCKET`

`doc_id` format: `<source_name>_<chunk_index>` (e.g., `laya_policy_guide_12`)

---

### 3.5 `rag_retrieval` (deployed as `insuremail-ai-dev-rag-retrieval`)

**Purpose**: Embed a query, scan DynamoDB for all vectors, return top-3 by cosine
similarity.

**Key env vars**: `EMBEDDINGS_TABLE_NAME`

> **Note**: The embeddings table uses paginated scan (1 MB DynamoDB page limit). The
> Lambda handles `LastEvaluatedKey` internally.

---

### 3.6 `email_sender` (deployed as `insuremail-ai-dev-email-sender`)

**Purpose**: Send the LLM-generated reply via Amazon SES, update DynamoDB status.

**Trigger**: Step Functions (SendResponse state) or direct Lambda invocation from
`api_handlers` (manual Send button in the dashboard).

**Key env vars**: `EMAIL_TABLE_NAME`, `SES_SENDER_EMAIL`

---

### 3.7 `api_handlers` (deployed as `insuremail-ai-dev-api-handlers`)

**Purpose**: REST API backend for the React dashboard.

**Key env vars**:

| Variable | Purpose |
|----------|---------|
| `EMAIL_TABLE_NAME` | DynamoDB email processing table |
| `MODEL_METRICS_TABLE_NAME` | DynamoDB model metrics table |
| `EMBEDDINGS_TABLE_NAME` | DynamoDB RAG embeddings table |
| `CLASSIFY_INTENT_FUNCTION_NAME` | Lambda name for model toggle |
| `CLAUDE_RESPONSE_FUNCTION_NAME` | Lambda name for model toggle |
| `EMAIL_SENDER_FUNCTION_NAME` | Lambda name for manual send |

See §6 for the full API reference.

---

## 4. Step Functions Workflow

State machine: `step-functions/email_processing_workflow.json`

```
ParseEmail
    │
    ▼
Parallel (ClassifyAndRetrieve)
    ├── Branch 0: ClassifyIntent   → $.analysis[0].intent
    └── Branch 1: RetrieveKnowledge → $.analysis[1].rag
                      │
                      └── (Catch) → SetEmptyRAG
                                    {retrieved_documents: [], statusCode: 200}
    │
    ▼
ValidateCRM  (pass-through for now)
    │
    ▼
GenerateResponse   ← uses $.analysis[0].intent.classification (full dict)
    │               and $.analysis[0].intent.rag_results
    │
    ├── (Catch) → HandleError
    │
    ▼
StoreResults
    │
    ▼
EvaluateResponse
    │
    ▼
SendResponse   (only if action == 'auto_response')
```

**Key data paths**:

| Parameter | JSONPath |
|-----------|----------|
| Full classification dict | `$.analysis[0].intent.classification` |
| RAG results | `$.analysis[0].intent.rag_results` |
| Customer intent string | `$.analysis[0].intent.classification.customer_intent` |

---

## 5. DynamoDB Table Schemas

### Email Processing Table (`insuremail-ai-dev-email-processing`)

Primary key: `email_id` (String, UUID)

| Field | Type | Notes |
|-------|------|-------|
| `email_id` | String | PK, UUID |
| `thread_id` | String | |
| `message_index` | Number | Position in thread |
| `sender_name` | String | |
| `sender_email` | String | |
| `mailbox` | String | Recipient address |
| `channel` | String | `email`, `gmail_imap` |
| `subject` | String | |
| `body_text` | String | Cleaned plain text |
| `received_at` | String | ISO 8601 |
| `detected_language` | String | `en`, `fr`, etc. |
| `processing_status` | String | `parsed`, `processing`, `completed`, `error` |
| `customer_intent` | String | One of 17 laya intents |
| `secondary_intent` | String | Optional |
| `business_line` | String | |
| `urgency` | String | `low`, `normal`, `high`, `critical` |
| `sentiment` | String | `positive`, `neutral`, `negative` |
| `gold_route_team` | String | Routing team |
| `gold_priority` | String | |
| `requires_human_review` | Boolean | |
| `classification_timestamp` | String | ISO 8601 |
| `confidence_score` | Decimal | 0.0 – 1.0 |
| `confidence_level` | String | `high`, `medium`, `low` |
| `action` | String | `auto_response`, `human_review`, `escalate` |
| `response_timestamp` | String | ISO 8601 |
| `llm_response` | String | Generated reply text |
| `reference_ids` | List | Doc IDs used by RAG |
| `policy_number` | String | Extracted entity |
| `member_id` | String | Extracted entity |
| `customer_id` | String | Extracted entity |
| `has_attachment` | Boolean | |
| `attachment_count` | Number | |
| `medical_terms_present` | Boolean | |
| `pii_present` | Boolean | |
| `s3_bucket` | String | Raw email location |
| `s3_key` | String | Raw email location |

### Model Metrics Table (`insuremail-ai-dev-model-metrics`)

Primary key: `metric_key` (String)
`metric_key` format: `{model_id}#{task_type}#{email_id}`

| Field | Type | Notes |
|-------|------|-------|
| `metric_key` | String | PK |
| `model_id` | String | Bedrock model ID |
| `model_name` | String | Short name (`mistral-7b`, `llama-3.1-8b`) |
| `task_type` | String | `email_classification`, `accuracy_evaluation`, `response_generation`, `response_evaluation` |
| `email_id` | String | Reference to email |
| `timestamp` | String | ISO 8601 |
| `latency_ms` | Decimal | |
| `cost_usd` | Decimal | |
| `accuracy_scores` | Map | `{customer_intent, urgency, …}` — only for `accuracy_evaluation` |
| `overall_accuracy` | Decimal | 0.0–1.0 — only for `accuracy_evaluation` |
| `eval_scores` | Map | `{faithfulness, answer_relevance, …}` — only for `response_evaluation` |
| `confidence_score` | Decimal | 0.0–1.0 — only for `response_evaluation` |

### Embeddings Table (`insuremail-ai-dev-embeddings`)

Primary key: `doc_id` (String)

| Field | Type | Notes |
|-------|------|-------|
| `doc_id` | String | PK, format: `{source_name}_{chunk_index}` |
| `content` | String | Chunk text |
| `embedding` | List | 1536 floats (Titan) |
| `source` | String | Original file name |
| `chunk_index` | Number | Position in source |

---

## 6. API Reference

Base URL: `https://{api-id}.execute-api.us-east-1.amazonaws.com/dev`

All endpoints return JSON. CORS headers are included on every response.

### Dashboard

#### `GET /api/dashboard/overview`

Returns aggregate stats for the overview page.

```json
{
  "total_emails": 42,
  "avg_confidence": 0.834,
  "auto_response_rate": 0.71,
  "confidence_distribution": {
    "high": 30,
    "medium": 8,
    "low": 4
  }
}
```

### Emails

#### `GET /api/emails`

Query params (all optional):

| Param | Values |
|-------|--------|
| `confidence_level` | `high`, `medium`, `low`, `pending` |
| `action` | `auto_response`, `human_review`, `escalate` |
| `processing_status` | `completed`, `parsed`, `processing`, `error` |

Response: `{ "emails": [ {...}, ... ] }` — array of email records (all fields from DynamoDB).

#### `GET /api/email/{emailId}`

Returns the full record for a single email (all 37 fields).

#### `POST /api/email/{emailId}`

Update the generated response text (save draft).

Request body: `{ "llm_response": "Dear Customer, ..." }`

Response: `{ "message": "Updated successfully" }`

#### `POST /api/email/{emailId}/send`

Invoke `email_sender` Lambda to send the current `llm_response` to `sender_email`.

Request body: `{}` (no body required)

Response: `{ "message": "Email sent successfully" }`

### Metrics

#### `GET /api/metrics/models`

```json
{
  "total_records": 16,
  "by_task": {
    "email_classification": {
      "count": 4,
      "models": ["mistral-7b"],
      "avg_latency_ms": 1230.5,
      "avg_cost_usd": 0.000021,
      "total_cost_usd": 0.000084
    },
    "accuracy_evaluation": {
      "count": 4,
      "avg_overall_accuracy": 0.714,
      "avg_field_accuracy": {
        "customer_intent": 0.75,
        "urgency": 0.82,
        ...
      },
      ...
    },
    "response_generation": { ... },
    "response_evaluation": {
      "avg_confidence_score": 0.81,
      "avg_eval_scores": {
        "faithfulness": 0.88,
        "answer_relevance": 0.79,
        ...
      },
      ...
    }
  },
  "by_model": {
    "mistral-7b": { "count": 8, "total_cost_usd": 0.0002, "avg_latency_ms": 1100 },
    "llama-3.1-8b": { "count": 8, "total_cost_usd": 0.0001, "avg_latency_ms": 950 }
  },
  "records": [ ... ]   // raw DynamoDB items, Decimals converted to float
}
```

#### `GET /api/metrics/rag`

```json
{
  "total_chunks": 320,
  "total_source_files": 177,
  "chunks_per_file": {
    "laya_policy_guide": 48,
    "claims_handbook": 32,
    ...
  },
  "status": "active"
}
```

### Settings

#### `GET /api/settings`

Returns the active model for each managed Lambda.

```json
{
  "classify_intent": "mistral-7b",
  "claude_response": "mistral-7b"
}
```

#### `POST /api/settings`

Toggle the active model for a Lambda (updates `ACTIVE_MODEL` env var).

Request body: `{ "classify_intent": "llama-3.1-8b" }` (one key at a time)

Valid values: `mistral-7b`, `llama-3.1-8b`

---

## 7. Frontend Development

### Dev server

```bash
cd dashboard/frontend
npm run dev       # Vite dev server at http://localhost:5173
```

The API URL is read from `VITE_API_BASE_URL` in `.env`. For local testing against
the deployed API, set it to the API Gateway URL.

### Adding a page

1. Create `src/pages/MyPage.jsx`:
```jsx
import React, { useState, useEffect } from 'react'
import axios from 'axios'

function MyPage({ apiUrl }) {
  const [data, setData] = useState(null)
  useEffect(() => { axios.get(`${apiUrl}/api/...`).then(r => setData(r.data)) }, [])
  if (!data) return <div className="loading">Loading...</div>
  return <div>...</div>
}

export default MyPage
```

2. Add route in `src/App.jsx`:
```jsx
import MyPage from './pages/MyPage'
// inside <Routes>:
<Route path="/my-page" element={<MyPage apiUrl={apiUrl} />} />
```

3. Add nav link in the `<nav>` section of `App.jsx`.

### Charts

Using [Recharts](https://recharts.org/):
```jsx
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

<ResponsiveContainer width="100%" height={260}>
  <BarChart data={data}>
    <CartesianGrid strokeDasharray="3 3" />
    <XAxis dataKey="name" />
    <YAxis />
    <Tooltip />
    <Bar dataKey="value" fill="#667eea" radius={[4,4,0,0]} />
  </BarChart>
</ResponsiveContainer>
```

### Build and deploy

```bash
npm run build                                         # outputs dist/
aws s3 sync dist/ s3://insuremail-ai-dashboard --delete
aws cloudfront create-invalidation \
    --distribution-id E2ADYLCS9LNMWF \
    --paths "/index.html"
```

Only `index.html` needs CloudFront invalidation; all JS/CSS assets are content-hashed
and automatically cache-busted by Vite.

---

## 8. Evaluation Pipeline

### Laya synthetic dataset

Located in `tests/test_data/laya_synthetic_dataset_starter/`. Four JSONL files:

| File | Records | Key fields |
|------|---------|-----------|
| `emails.jsonl` | 1000 | `email_id`, `customer_intent` (17 classes), `gold_route_team` (12 teams), `requires_human_review` |
| `cases.jsonl` | 1000 | `email_id`, `rag_context_group`, `draft_response_id` |
| `draft_responses.jsonl` | 1000 | `draft_response_id`, `generated_reply`, `grounded_doc_ids` |
| `attachment_content.jsonl` | 1044 | `doc_category` (14 types), `raw_text`, `structured_gold_fields` |

### Running evaluations

```bash
# 1. Generate eval JSONL datasets (model_eval + rag_eval, 100 records each)
python scripts/generate_eval_datasets.py
python scripts/generate_eval_datasets.py --upload   # also upload to S3 eval-datasets/

# 2. Local evaluation (intent, routing, confidence calibration, entity extraction)
python scripts/run_local_evaluation.py               # default: 50 emails, 30 attachments
python scripts/run_local_evaluation.py --n-emails 100 --n-attachments 50
python scripts/run_local_evaluation.py --dry-run     # mock data, no Bedrock calls

# 3. Full pipeline (generate → local eval → submit Bedrock eval jobs)
python scripts/run_full_evaluation.py
```

Results are saved to `results/eval_report_<timestamp>.json`.

### Target metrics

| Dimension | Metric | Target |
|-----------|--------|--------|
| Intent classification | Accuracy | ≥ 85% |
| Intent classification | Macro-avg F1 | ≥ 0.80 |
| Routing | Routing accuracy | ≥ 88% |
| Confidence calibration | Missed-escalation rate | < 2% |
| Confidence calibration | False-escalation rate | < 15% |
| RAG response quality | Correctness / Helpfulness (LLM-as-judge) | ≥ 0.75 |

---

## 9. Deployment Cheatsheet

### Deploy a single Lambda

```bash
cd lambda/<function_name>
zip -r /tmp/<fn>.zip lambda_function.py
aws lambda update-function-code \
    --function-name insuremail-ai-dev-<deployed-name> \
    --zip-file fileb:///tmp/<fn>.zip
aws lambda wait function-updated --function-name insuremail-ai-dev-<deployed-name>
```

### Lambda deployed names

| Source directory | Deployed function name |
|-----------------|----------------------|
| `classify_intent` | `insuremail-ai-dev-multi-llm-inference` |
| `claude_response` | `insuremail-ai-dev-claude-response` |
| `email_parser` | `insuremail-ai-dev-email-parser` |
| `email_sender` | `insuremail-ai-dev-email-sender` |
| `rag_ingestion` | `insuremail-ai-dev-rag-ingestion` |
| `rag_retrieval` | `insuremail-ai-dev-rag-retrieval` |
| `api_handlers` | `insuremail-ai-dev-api-handlers` |

### Update Step Functions state machine

```bash
STATE_MACHINE_ARN=$(aws stepfunctions list-state-machines \
    --query "stateMachines[?name=='insuremail-ai-dev-email-processor'].stateMachineArn" \
    --output text)
aws stepfunctions update-state-machine \
    --state-machine-arn "$STATE_MACHINE_ARN" \
    --definition file://step-functions/email_processing_workflow.json
```

### Full Terraform deploy

```bash
cd terraform
terraform plan -out=tfplan
terraform apply tfplan
```

### Makefile shortcuts

```bash
make test            # all tests
make test-unit       # unit tests only
make test-coverage   # tests + HTML coverage report (open htmlcov/index.html)
make lint            # flake8 + black check
make fmt             # auto-format with black
make check           # lint + fast tests (pre-commit quick check)
make ci              # full CI simulation (clean → install → lint → test → tf-validate)
make tf-plan         # terraform plan
make tf-apply        # terraform apply (with confirmation prompt)
make dashboard-build # npm run build
```

---

## 10. Testing

### Run tests

```bash
# All tests (unit + integration + terraform)
pytest tests/ -v

# Unit only
pytest tests/unit/ -v

# Single file
pytest tests/unit/test_api_handlers.py -v

# Stop on first failure
pytest tests/ -x

# With coverage
pytest tests/ --cov=lambda --cov-report=html
open htmlcov/index.html
```

### Test infrastructure

- **Mocking AWS**: uses `moto` v5+. Import `from moto import mock_aws` (not the old
  per-service decorators like `mock_dynamodb`).
- **Env vars**: set at module level in `tests/conftest.py` via `os.environ.setdefault`
  before any Lambda imports.
- **Module collision**: multiple Lambdas are all named `lambda_function`. Tests that
  import more than one Lambda use `sys.modules.pop('lambda_function', None)` before each
  import.
- **DynamoDB numbers**: moto returns `Decimal` for all numeric fields. Use `float(x)` or
  `int(x)` in assertions; do not use `isinstance(x, int)`.

### Coverage target

**78%** (current), minimum threshold enforced by `pytest.ini`: `--cov-fail-under=70`

---

## 11. Known Pitfalls

### DynamoDB reserved words

`action` is a DynamoDB reserved word. Using it with manual `ExpressionAttributeNames`
*and* boto3's `Attr()` condition builder at the same time causes:

```
ValidationException: Value provided in ExpressionAttributeNames unused
```

**Fix**: use `Attr('action').eq(value)` — boto3's condition builder handles reserved
word escaping internally without any manual `ExpressionAttributeNames`.

### DynamoDB scan pagination

The embeddings table has 320 items each with a 1536-float vector. A single scan hits
the 1 MB DynamoDB page limit and returns only ~32 items.

**Fix**: always paginate:
```python
items, kwargs = [], {}
while True:
    resp = table.scan(**kwargs)
    items.extend(resp.get('Items', []))
    if not (last := resp.get('LastEvaluatedKey')):
        break
    kwargs['ExclusiveStartKey'] = last
```

### Step Functions data paths

After a Parallel state, the output is a list indexed by branch order.
Branch 0 (ClassifyIntent) sets `ResultPath: $.intent`, so the full classification
dict is at `$.analysis[0].intent.classification`, not `$.analysis[0].classification`.

### CloudFront caching

After `aws s3 sync`, `index.html` is not automatically invalidated. JS/CSS files are
content-hashed and cache-bust automatically, but `index.html` itself must be
invalidated after every deploy:
```bash
aws cloudfront create-invalidation --distribution-id E2ADYLCS9LNMWF --paths "/index.html"
```

### Bedrock model IDs

| Short name | Bedrock model ID |
|-----------|-----------------|
| Claude 3 Sonnet (primary) | `anthropic.claude-3-sonnet-20240229-v1:0` |
| Claude 3 Haiku (eval judge) | `anthropic.claude-3-haiku-20240307-v1:0` |
| Mistral 7B | `mistral.mistral-7b-instruct-v0:2` |
| Llama 3.1 8B | `meta.llama3-8b-instruct-v1:0` |
| Titan Embeddings | `amazon.titan-embed-text-v1` |

Claude Sonnet uses the `messages` API format (`anthropic_version: bedrock-2023-05-31`).
Mistral and Llama use a prompt-string format. They are **not interchangeable** request
bodies.

### IAM for Lambda management

The `api_handlers` Lambda needs these extra IAM permissions to support the Model
Settings toggle and the Send button:

```json
{
  "Action": [
    "lambda:GetFunctionConfiguration",
    "lambda:UpdateFunctionConfiguration",
    "lambda:InvokeFunction"
  ],
  "Resource": [
    "arn:aws:lambda:us-east-1:*:function:insuremail-ai-dev-multi-llm-inference",
    "arn:aws:lambda:us-east-1:*:function:insuremail-ai-dev-claude-response",
    "arn:aws:lambda:us-east-1:*:function:insuremail-ai-dev-email-sender"
  ]
}
```

These are attached as an inline policy `insuremail-ai-dev-lambda-manage` on the
`insuremail-ai-dev-lambda-execution` role.
