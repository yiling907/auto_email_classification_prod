# InsureMail AI — Accuracy Metrics

This document describes the accuracy metrics and evaluation methodology used across the InsureMail AI pipeline.

## Table of Contents

1. [Intent Classification](#intent-classification)
2. [RAG Retrieval](#rag-retrieval)
3. [Response Generation](#response-generation)
4. [Claim Form Extraction](#claim-form-extraction)
5. [End-to-End Pipeline Assessment](#end-to-end-pipeline-assessment)
6. [Thresholds & Pass/Fail Criteria](#thresholds--passfail-criteria)
7. [Running Evaluations](#running-evaluations)

---

## Intent Classification

**Script**: `scripts/run_intent_eval.py`

**Purpose**: Evaluate the accuracy of classifying incoming emails into 17 intent categories and routing to 12 specialist teams.

### Primary Metrics

| Metric | Definition | Threshold | Status |
|---|---|---|---|
| **Accuracy** | % of emails correctly classified | ≥ 0.80 | PASSED |
| **Macro F1** | Average F1 score across all 17 intents | — | Reported |
| **Routing Accuracy** | % of emails routed to correct team | — | Derived from intent |

### Per-Class Metrics

For each of the 17 intent classes:

- **Precision**: `TP / (TP + FP)` — fraction of predicted intents that are correct
- **Recall**: `TP / (TP + FN)` — fraction of true intents that were found
- **F1**: `2 × (Precision × Recall) / (Precision + Recall)` — harmonic mean
- **Support**: Number of test samples for this intent class

### Per-Team Routing

For each of the 12 routing teams, reports the accuracy of emails routed to that team:

```
customer_support_team         0.920  ████████████████████
claims_team                   0.850  █████████████████
medical_review_team           0.780  ███████████████
...
```

### Additional Outputs

- **Top Confused Pairs**: Shows the most common misclassifications
  - Example: `coverage_query → claim_status (n=5)`
- **Latency**: Average response time in milliseconds per email

### Intent Classes (17 total)

```
coverage_query
claim_submission
claim_status
claim_reimbursement_query
pre_authorisation
payment_issue
policy_change
renewal_query
cancellation_request
enrollment_new_policy
dependent_addition
complaint
document_followup
hospital_network_query
id_verification
broker_query
other
```

---

## RAG Retrieval

**Script**: `scripts/run_rag_eval.py`

**Purpose**: Evaluate the semantic search and document retrieval component that grounds responses in the knowledge base.

### Primary Metrics

| Metric | Definition | Threshold | Status |
|---|---|---|---|
| **Hit Rate** | % of emails with ≥1 relevant doc retrieved | ≥ 0.60 | PASSED |
| **Empty Retrieval Rate** | `1 - hit_rate` (inverse) | — | Reported |
| **Avg Docs Retrieved** | Mean # documents returned per query | — | Reported |
| **Avg Doc Precision** | % of retrieved docs matching gold labels | — | Reported |

### Relevance Threshold

A document is considered **relevant** if its cosine similarity score ≥ **0.70** (configurable in script).

### Per-Intent Hit Rate

Hit rate breakdown by customer intent:

```
coverage_query              0.750  ███████████████
claim_status                0.680  █████████████
payment_issue               0.620  ████████████
...
```

### Methodology

1. For each test email, extract the intent and email body
2. Invoke `rag_retrieval` Lambda with top_k=5
3. Compare retrieved doc IDs against gold grounded_doc_ids from draft_responses.jsonl
4. Calculate precision: (# retrieved docs in gold set) / (# retrieved docs above threshold)

### Gold Data

Gold document groundings come from:
- **cases.jsonl**: Maps email_id → draft_response_id
- **draft_responses.jsonl**: Contains `grounded_doc_ids` (list of reference doc IDs)

---

## Response Generation

**Script**: `scripts/run_response_eval.py`

**Purpose**: Evaluate the quality of AI-generated customer service responses.

### Primary Metrics

| Metric | Definition | Threshold | Status |
|---|---|---|---|
| **Avg LLM Judge Score** | Mistral 7B quality score (0.0–1.0) | — | Reported |
| **Escalation Agreement** | % of human-review emails correctly flagged | ≥ 0.70 | PASSED |
| **Hedge Rate** | % of responses with polite/cautious phrases | — | Reported |
| **Response Coverage Rate** | % of emails with generated responses | — | Reported |

### LLM Judge Scoring

Uses **Mistral 7B** to evaluate responses on a 0.0–1.0 scale across four dimensions:

1. **Relevance**: Does it address the same issue?
2. **Accuracy**: Are facts/positions consistent with gold standard?
3. **Completeness**: Are key points covered?
4. **Professionalism**: Appropriate tone for insurance customer service?

Judge returns a JSON object:
```json
{
  "score": 0.85,
  "reason": "Addresses claim status clearly but missing policy number confirmation"
}
```

### Hedge Phrases Detected

```
"please"
"kindly"
"if you have"
"do not hesitate"
"thank you"
"we understand"
"we apologise" / "we apologize"
"feel free"
"should you"
"for your convenience"
```

### Escalation Agreement

Measures whether the pipeline correctly identifies emails requiring human review:

- **Gold Labels**: `requires_human_review` from emails.jsonl
- **Pipeline Prediction**: Routing decision (human_review / escalate vs. auto_response)
- **Agreement**: % match between gold and predicted escalation

Threshold: ≥ 0.70 for PASS

### Per-Intent Breakdown

Reports average LLM judge score for each intent class.

### Methodology

1. Load the most recent `stepfn_assessment_*.json` from results/
2. Join pipeline responses against gold draft_responses.jsonl via email_id
3. For each email with both predicted and gold response:
   - Invoke LLM judge
   - Record score, hedge rate, escalation agreement
4. Aggregate and report metrics

---

## Claim Form Extraction

**Script**: `scripts/run_claim_extraction_eval.py`

**Purpose**: Evaluate structured field extraction from Laya Healthcare out-patient claim forms.

### Field Types & Metrics

#### String Fields (26 fields)

Examples: `membership_no`, `surname`, `forenames`, `date_of_birth`, `telephone`, `correspondence_address`, `mri_date`, etc.

**Per-Field Metrics**:

| Metric | Definition |
|---|---|
| **Exact Match** | String equality (case-insensitive after normalization) |
| **Partial Match** | Token-overlap F1 ≥ 0.5 |
| **Precision** | `TP_partial / (TP_partial + FP)` |
| **Recall** | `TP_partial / (TP_partial + FN)` |
| **F1** | `2 × (Precision × Recall) / (Precision + Recall)` |
| **Support** | Number of test samples with this field present in gold |

**True Negatives (TN)** counted when both gold and predicted are absent.

#### Boolean Fields (3 fields)

Examples: `expenses_recoverable`, `recovery_via_solicitor`, `recovery_via_piab`

**Metrics**: Exact match (boolean equality) + TP/FP/FN accounting

#### Numeric Fields (2 fields)

Examples: `receipts_total_cost`, `dental_cost`

**Metrics**:

| Metric | Definition |
|---|---|
| **Within 5% Tolerance** | `abs(predicted - gold) ≤ 0.05 × gold` |
| **Mean Absolute Error (MAE)** | Average absolute difference in dollars |

#### Structured Arrays

**Receipts** (List of treatment receipt objects):

- Per-row matching on treatment type and cost
- **Treatment F1**: Precision/recall of correctly extracted rows
- **Cost Accuracy**: % of receipts within ±5% cost tolerance

**Dependants** (List of dependent names):

- Matching via token-overlap F1 ≥ 0.5
- **Name TP**: Correctly extracted dependant names
- **Name FP**: Predicted names not in gold
- **Name FN**: Gold names not extracted

### Overall Weighted Score

**Range**: 0.0 to 1.0

**Composition**:

```
30% — Core identity fields
        (surname, forenames, membership_no, date_of_birth)

20% — Payment fields
        (account_holder_name, account_number, bank_sort_code, bank_name_address)

20% — Receipts
        (treatment F1 + cost accuracy) / 2

20% — Specialist sections
        (MRI, accident, dental fields)

10% — Dependants + boolean fields
        (dependants F1 + bool fields F1) / 2
```

Each component uses **partial match F1** (not exact match) for more lenient scoring.

### Test Scenarios

Gold dataset organized by scenario type:

| Scenario | Label | Description |
|---|---|---|
| `gp_physio_receipts` | GP/physio receipts | Claims with treatment receipts |
| `accident_section` | Accident section | Third-party accident details |
| `dental_emergency` | Dental emergency | Dental claim scenarios |
| `mri_scan` | MRI/scan referral | Radiology referrals |
| `dependant_claim` | Dependant claims | Claims with dependants |
| `incomplete_form` | Incomplete forms | Partial/sparse forms |

### Bedrock Retry Strategy

- **Max Retries**: 1
- **Retry Delay**: 5 seconds (handles throttling)

---

## End-to-End Pipeline Assessment

**Script**: `scripts/run_stepfn_assessment.py`

**Purpose**: Evaluate the complete AWS Step Functions pipeline end-to-end, exercising all Lambda functions in sequence.

### Pipeline Execution Flow

```
Upload email to S3
       ↓
Start Step Function execution
       ↓
Poll until success/failure/timeout (120 sec max)
       ↓
Extract predictions from execution output
       ↓
Score against gold labels
```

### Composite Pipeline Score

**Threshold**: ≥ 0.70 for PASS (exit code 0)

**Components**:

1. **Intent Classification Accuracy** — % correct 17-way intent classification
2. **Routing Accuracy** — % emails routed to correct team
3. **Confidence Calibration** — how well confidence scores reflect actual correctness
4. **Response Quality** — LLM judge score for generated response
5. **Escalation Routing** — % of human-review emails correctly identified

Weighted average of above components (weights determined by pipeline importance).

### Per-Email Results

For each test email, the assessment captures:

```json
{
  "email_id": "laya_12345",
  "gold_intent": "claim_status",
  "predicted_intent": "claim_status",
  "gold_route": "claims_team",
  "predicted_route": "claims_team",
  "confidence_score": 0.92,
  "response_text": "Your claim #... is being processed...",
  "action": "auto_response",
  "latency_ms": 1245,
  "error": null
}
```

### Configuration

```python
PASS_THRESHOLD      = 0.70      # Composite score threshold
EXEC_TIMEOUT_SEC    = 120       # Max wait per execution
POLL_INTERVAL_SEC   = 3         # Status poll frequency
S3_PREFIX           = "test-pipeline"  # S3 key for test emails
```

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | Composite score ≥ 0.70 — PASS |
| `1` | Score < 0.70, execution errors, or unrecoverable failure — FAIL |

### Usage

```bash
# 20-email quick smoke test
python scripts/run_stepfn_assessment.py --sample 20

# 50-email standard run
python scripts/run_stepfn_assessment.py --sample 50

# Full 1000-email run with 10 concurrent executions
python scripts/run_stepfn_assessment.py --sample 0 --concurrency 10
```

---

## Thresholds & Pass/Fail Criteria

### Summary Table

| Task | Metric | Threshold | Pass Criterion |
|---|---|---|---|
| **Intent Classification** | Accuracy | ≥ 0.80 | Accuracy >= threshold |
| **Routing** | Accuracy | — | Reported (derived from intent) |
| **RAG Retrieval** | Hit Rate | ≥ 0.60 | Hit rate >= threshold |
| **Response Generation** | Escalation Agreement | ≥ 0.70 | Agreement >= threshold |
| **Claim Extraction** | Overall Score | — | Reported (no hard threshold) |
| **Pipeline E2E** | Composite Score | ≥ 0.70 | Composite >= threshold |

### Pass/Fail Reporting

Each evaluation script prints a status line:

```
Intent Accuracy : 0.8450  [PASSED]  (threshold=0.80)
Hit Rate        : 0.6200  [PASSED]  (threshold=0.60)
Escalation Agr. : 0.7150  [PASSED]  (threshold=0.70)
```

---

## Running Evaluations

### Quick Start

Run all evaluations in sequence:

```bash
# Intent classification (50 emails)
python scripts/run_intent_eval.py --sample 50

# RAG retrieval (30 emails)
python scripts/run_rag_eval.py --sample 30

# Response generation (requires prior assessment)
python scripts/run_stepfn_assessment.py --sample 50
python scripts/run_response_eval.py

# Claim extraction (all records in dataset)
python scripts/run_claim_extraction_eval.py --limit 100
```

### Output Files

Each script writes results to `results/` with timestamps:

```
results/
├── intent_eval_20260327_143022.json
├── rag_eval_20260327_143045.json
├── response_eval_20260327_143102.json
├── claim_extraction_eval_20260327_143120.json
└── stepfn_assessment_20260327_143010.json
```

### S3 Upload

All evaluations automatically upload to:

```
s3://insuremail-ai-dev-logs/eval_reports/
├── intent_eval_latest.json
├── rag_eval_latest.json
├── response_eval_latest.json
├── claim_extraction_eval_latest.json
└── assessment/latest.json
```

### Test Data

Gold dataset located at:

```
tests/test_data/laya_synthetic_dataset_starter/
├── emails.jsonl              # 1000 emails with gold intent labels
├── cases.jsonl               # 1000 case records linking emails to responses
├── draft_responses.jsonl     # 1000 gold response texts + doc groundings
└── DATA_SCHEMA.md            # Field definitions
```

### Environment Variables

```bash
# AWS configuration
export AWS_REGION=us-east-1
export EMAIL_BUCKET=insuremail-ai-dev-emails
export RESULTS_BUCKET=insuremail-ai-dev-logs
export EMAIL_TABLE_NAME=insuremail-ai-dev-email-processing
export STATE_MACHINE_ARN=arn:aws:states:us-east-1:970850578809:stateMachine:insuremail-ai-dev-email-processing

# Lambda function names (optional, auto-resolved by default)
export INTENT_LAMBDA=insuremail-ai-dev-classify-intent-by-llm
export RAG_LAMBDA=insuremail-ai-dev-rag-retrieval
```

---

## Dashboard Integration

Evaluation results are displayed in the React dashboard at:

- **Model Metrics** tab: Intent accuracy, routing accuracy, macro F1
- **RAG Metrics** tab: Hit rate, avg docs, doc precision per intent
- **Evaluations** tab: Response quality scores, escalation agreement, claim extraction results

The dashboard fetches latest results from S3 and DynamoDB `model_metrics` table.

---

## Gotchas & Caveats

1. **Email Module Loading** (`run_claim_extraction_eval.py`): Must set `EMAIL_TABLE_NAME` env var before importing the Lambda module (it's required at import time).

2. **Gold Dataset Dependency**: Response and RAG evaluations require cases.jsonl and draft_responses.jsonl. If these are missing, those evaluations will skip gracefully.

3. **Bedrock Throttling**: Claim extraction and response evaluation invoke Bedrock multiple times. If throttled, scripts retry up to 1 time with 5-second backoff.

4. **Similarity Threshold**: RAG evaluation uses cosine similarity ≥ 0.70 to determine relevance. Lower threshold = more hits, higher threshold = stricter matching.

5. **Per-Class Imbalance**: Some intents have fewer gold examples (support < 5). Per-class F1 scores may be noisy.

6. **Latency Includes Network**: Pipeline assessment latency includes Step Function orchestration overhead, not just compute time.

---

## References

- **CLAUDE.md**: Development commands and conventions
- **DEVELOPMENT.md**: Detailed Lambda function internals
- **tests/README.md**: Unit test patterns and fixtures
- **README.md**: Project overview and quick start
