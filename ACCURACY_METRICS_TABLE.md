# InsureMail AI — Accuracy Metrics by Task Type

Quick reference table of all accuracy metrics organized by evaluation task.

---

## Intent Classification (`run_intent_eval.py`)

| Metric | Definition | Threshold | Unit | Status |
|---|---|---|---|---|
| **Accuracy** | % emails correctly classified into 17 intents | ≥ 0.80 | float 0–1 | PASSED |
| **Macro F1** | Average F1 across all 17 intent classes | — | float 0–1 | Reported |
| **Routing Accuracy** | % emails routed to correct team (12 teams) | — | float 0–1 | Derived from intent |
| **Latency** | Average response time per email | — | milliseconds | Reported |

### Per-Intent Metrics (17 classes)

| Metric | Definition | Notes |
|---|---|---|
| **Precision (per intent)** | TP / (TP + FP) | Fraction of predicted intents that are correct |
| **Recall (per intent)** | TP / (TP + FN) | Fraction of true intents found |
| **F1 (per intent)** | 2 × (P × R) / (P + R) | Harmonic mean of precision & recall |
| **Support (per intent)** | Count of samples | Number of test emails with this intent |

### Per-Team Routing Metrics (12 teams)

| Team | Accuracy | Notes |
|---|---|---|
| customer_support_team | float 0–1 | Coverage queries |
| claims_team | float 0–1 | Claims submissions, status, reimbursement |
| medical_review_team | float 0–1 | Pre-authorizations |
| finance_support_team | float 0–1 | Payment issues |
| policy_admin_team | float 0–1 | Policy changes, dependent additions |
| renewals_team | float 0–1 | Renewal queries |
| retention_team | float 0–1 | Cancellation requests |
| sales_enrollment_team | float 0–1 | New policy enrollment |
| complaints_team | float 0–1 | Complaints |
| operations_team | float 0–1 | Document follow-up, ID verification |
| provider_support_team | float 0–1 | Hospital network queries |
| general_support_team | float 0–1 | Broker queries, other |

### Intent Classes (17 total)

| Intent | Route Team | Example |
|---|---|---|
| coverage_query | customer_support_team | "What's covered?" |
| claim_submission | claims_team | "I'm submitting a claim" |
| claim_status | claims_team | "Where's my claim?" |
| claim_reimbursement_query | claims_team | "When will I be reimbursed?" |
| pre_authorisation | medical_review_team | "I need pre-auth for surgery" |
| payment_issue | finance_support_team | "Payment not received" |
| policy_change | policy_admin_team | "Change beneficiary" |
| renewal_query | renewals_team | "When does policy renew?" |
| cancellation_request | retention_team | "I want to cancel" |
| enrollment_new_policy | sales_enrollment_team | "Sign me up" |
| dependent_addition | policy_admin_team | "Add dependent" |
| complaint | complaints_team | "I'm not satisfied" |
| document_followup | operations_team | "Missing documents" |
| hospital_network_query | provider_support_team | "Is X hospital in network?" |
| id_verification | operations_team | "Verify my identity" |
| broker_query | general_support_team | "Agent question" |
| other | general_support_team | Unclassified |

---

## RAG Retrieval (`run_rag_eval.py`)

| Metric | Definition | Threshold | Unit | Status |
|---|---|---|---|---|
| **Hit Rate** | % emails with ≥1 relevant document | ≥ 0.60 | float 0–1 | PASSED |
| **Empty Retrieval Rate** | 1 - hit_rate (inverse) | — | float 0–1 | Reported |
| **Avg Docs Retrieved** | Mean # documents per query | — | float ≥ 0 | Reported |
| **Avg Doc Precision** | % retrieved docs matching gold IDs | — | float 0–1 | Reported |
| **Relevance Threshold** | Cosine similarity cutoff | = 0.70 | float 0–1 | Configurable |

### Per-Intent Hit Rate (17 intents)

| Intent | Hit Rate | Notes |
|---|---|---|
| coverage_query | float 0–1 | Avg hit rate for this intent class |
| claim_status | float 0–1 | ... |
| (all 17 intents) | float 0–1 | Breakdown by customer intent |

### Gold Data Source

| File | Purpose | Fields |
|---|---|---|
| emails.jsonl | Test email corpus | email_id, body_text, subject, customer_intent |
| cases.jsonl | Email ↔ Response mapping | email_id, draft_response_id |
| draft_responses.jsonl | Gold responses & groundings | draft_response_id, generated_reply, **grounded_doc_ids** |

---

## Response Generation (`run_response_eval.py`)

| Metric | Definition | Threshold | Unit | Status |
|---|---|---|---|---|
| **Avg LLM Judge Score** | Mistral 7B response quality (0–1) | — | float 0–1 | Reported |
| **Escalation Agreement** | % human-review emails correctly flagged | ≥ 0.70 | float 0–1 | PASSED |
| **Hedge Rate** | % responses with polite/cautious phrases | — | float 0–1 | Reported |
| **Response Coverage Rate** | % emails with generated responses | — | float 0–1 | Reported |
| **Judge Model** | LLM used for quality scoring | — | string | mistral.mistral-7b-instruct-v0:2 |

### LLM Judge Scoring Dimensions

| Dimension | Definition | Scale |
|---|---|---|
| **Relevance** | Does it address the same issue? | 0.0–1.0 |
| **Accuracy** | Are facts/positions consistent with gold? | 0.0–1.0 |
| **Completeness** | Are key points covered? | 0.0–1.0 |
| **Professionalism** | Appropriate tone for insurance customer service? | 0.0–1.0 |
| **Overall Score** | Average of 4 dimensions | 0.0–1.0 |

### Hedge Phrases Detected

| Phrase | Category | Purpose |
|---|---|---|
| please, kindly | Politeness | Softens requests |
| if you have, should you | Conditional | Hedges certainty |
| do not hesitate, feel free | Encouragement | Invites action |
| thank you | Gratitude | Shows appreciation |
| we understand, we apologise/apologize | Empathy | Shows understanding |
| for your convenience | Service mindset | Customer-focused |

### Per-Intent LLM Judge Scores (17 intents)

| Intent | Avg Judge Score | Notes |
|---|---|---|
| coverage_query | float 0–1 | Average quality for this intent |
| claim_status | float 0–1 | ... |
| (all 17 intents) | float 0–1 | Breakdown by customer intent |

### Escalation Routing

| Condition | Action | Metric |
|---|---|---|
| Gold: requires_human_review = true | Should route to human_review / escalate | Escalation Agreement |
| Gold: requires_human_review = false | Should route to auto_response | Escalation Agreement |
| Agreement rate ≥ 0.70 | PASS threshold | Escalation Agreement |

---

## Claim Form Extraction (`run_claim_extraction_eval.py`)

### String Fields (26 fields)

| Field Name | Type | Match Type | Metrics | Notes |
|---|---|---|---|---|
| membership_no | string | Exact / Partial | Precision, Recall, F1, Support | ID field |
| surname | string | Exact / Partial | Precision, Recall, F1, Support | Identity field |
| forenames | string | Exact / Partial | Precision, Recall, F1, Support | Identity field |
| date_of_birth | string | Exact / Partial | Precision, Recall, F1, Support | Identity field |
| title | string | Exact / Partial | Precision, Recall, F1, Support | Mr/Mrs/Ms/Dr |
| telephone | string | Exact / Partial | Precision, Recall, F1, Support | Contact field |
| correspondence_address | string | Exact / Partial | Precision, Recall, F1, Support | Contact field |
| mri_date | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| mri_reason_for_referral | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| mri_centre | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| mri_procedure | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| mri_referring_gp | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| mri_consultant_code | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| accident_date | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| accident_description | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| third_party_details | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| dental_injury_date | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| dental_injury_place | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| dental_injury_description | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| dental_treatment_start | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| dental_treatment_end | string | Exact / Partial | Precision, Recall, F1, Support | Specialist section |
| account_holder_name | string | Exact / Partial | Precision, Recall, F1, Support | Payment field |
| account_number | string | Exact / Partial | Precision, Recall, F1, Support | Payment field |
| bank_sort_code | string | Exact / Partial | Precision, Recall, F1, Support | Payment field |
| bank_name_address | string | Exact / Partial | Precision, Recall, F1, Support | Payment field |
| declaration_date | string | Exact / Partial | Precision, Recall, F1, Support | Signature field |

#### String Field Metrics

| Metric | Definition | Formula |
|---|---|---|
| **Exact Match** | String equality (case-insensitive) | `predicted == gold` (normalized) |
| **Partial Match** | Token-overlap F1 ≥ 0.5 | Token F1(predicted, gold) ≥ 0.5 |
| **Precision** | Fraction of predictions that are correct | `TP_partial / (TP_partial + FP)` |
| **Recall** | Fraction of true labels found | `TP_partial / (TP_partial + FN)` |
| **F1** | Harmonic mean of precision & recall | `2 × (P × R) / (P + R)` |
| **Support** | Number of test samples | Count where gold value present |
| **True Negatives** | Both gold & predicted absent | Only counted if gold absent |

### Boolean Fields (3 fields)

| Field Name | Values | Metrics | Notes |
|---|---|---|---|
| expenses_recoverable | true / false | TP, FP, FN, Support | Recoverable expenses flag |
| recovery_via_solicitor | true / false | TP, FP, FN, Support | Third-party recovery flag |
| recovery_via_piab | true / false | TP, FP, FN, Support | PIAB recovery flag |

#### Boolean Field Metrics

| Metric | Definition | Formula |
|---|---|---|
| **Exact Match** | Boolean equality | `predicted == gold` |
| **Precision** | Fraction of positive predictions correct | `TP / (TP + FP)` |
| **Recall** | Fraction of true positives found | `TP / (TP + FN)` |
| **F1** | Harmonic mean | `2 × (P × R) / (P + R)` |
| **Support** | Number of test samples | Count where gold value present |

### Numeric Fields (2 fields)

| Field Name | Range | Tolerance | Metrics | Notes |
|---|---|---|---|---|
| receipts_total_cost | $0–$10k | ±5% | Within tolerance, MAE, Support | Receipt costs |
| dental_cost | $0–$5k | ±5% | Within tolerance, MAE, Support | Dental costs |

#### Numeric Field Metrics

| Metric | Definition | Formula |
|---|---|---|
| **Within 5% Tolerance** | Absolute error within 5% of gold | `abs(pred - gold) ≤ 0.05 × gold` |
| **Mean Absolute Error (MAE)** | Average absolute difference | `mean(abs(pred - gold))` |
| **Support** | Number of test samples | Count where gold value present |

### Structured Arrays

#### Receipts Array

| Subfield | Type | Match Criteria | Metrics |
|---|---|---|---|
| treatment_type | string | Token-overlap F1 ≥ 0.5 | TP, FP, FN |
| cost | numeric | Within ±5% | Within tolerance count |

**Metrics for Receipts**:

| Metric | Definition | Formula |
|---|---|---|
| **Treatment F1** | Row-level treatment matching | `2 × (P × R) / (P + R)` where P/R across rows |
| **Cost Accuracy** | % of rows within ±5% cost tolerance | `within_5pct / total_receipt_rows` |
| **Combined** | Avg of treatment F1 + cost accuracy | `(Treatment F1 + Cost Accuracy) / 2` |

#### Dependants Array

| Subfield | Type | Match Criteria | Metrics |
|---|---|---|---|
| name | string | Token-overlap F1 ≥ 0.5 | TP, FP, FN |

**Metrics for Dependants**:

| Metric | Definition | Formula |
|---|---|---|
| **Name TP** | Correctly extracted dependant names | Count matches with F1 ≥ 0.5 |
| **Name FP** | Predicted names not in gold | Count unmatched predictions |
| **Name FN** | Gold names not extracted | Count unmatched gold |
| **Dependants F1** | Row-level matching | `2 × (TP) / (2 × TP + FP + FN)` |

### Overall Weighted Score

| Component | Weight | Subcomponent | Metric Used |
|---|---|---|---|
| **Core Identity** | 30% | surname | F1 partial match |
| | | forenames | F1 partial match |
| | | membership_no | F1 partial match |
| | | date_of_birth | F1 partial match |
| **Payment** | 20% | account_holder_name | F1 partial match |
| | | account_number | F1 partial match |
| | | bank_sort_code | F1 partial match |
| | | bank_name_address | F1 partial match |
| **Receipts** | 20% | treatment_type | F1 |
| | | cost | Accuracy ±5% |
| **Specialist** | 20% | MRI fields (5) | Avg F1 partial match |
| | | Accident fields (3) | Avg F1 partial match |
| | | Dental fields (5) | Avg F1 partial match |
| **Dependants/Bool** | 10% | dependants | F1 |
| | | bool fields (3) | Avg F1 exact match |

**Formula**:
```
Overall Score =
  0.30 × avg(core_f1) +
  0.20 × avg(payment_f1) +
  0.20 × (treatment_f1 + cost_accuracy) / 2 +
  0.20 × avg(specialist_f1) +
  0.10 × (dependants_f1 + avg(bool_f1)) / 2
```

**Range**: 0.0 to 1.0

### Test Scenarios

| Scenario | Label | Description | Gold Records |
|---|---|---|---|
| GP/physio receipts | gp_physio_receipts | Treatment receipt claims | N records |
| Accident section | accident_section | Third-party accident details | N records |
| Dental emergency | dental_emergency | Dental claim scenarios | N records |
| MRI/scan referral | mri_scan | Radiology referrals | N records |
| Dependant claims | dependant_claim | Claims with dependants | N records |
| Incomplete forms | incomplete_form | Partial/sparse forms | N records |

---

## End-to-End Pipeline Assessment (`run_stepfn_assessment.py`)

| Metric | Definition | Threshold | Unit | Status |
|---|---|---|---|---|
| **Composite Score** | Weighted avg of all components | ≥ 0.70 | float 0–1 | PASSED |
| **Intent Accuracy** | % correct 17-way classification | — | float 0–1 | Component |
| **Routing Accuracy** | % routed to correct team | — | float 0–1 | Component |
| **Confidence Calibration** | How well confidence reflects correctness | — | float 0–1 | Component |
| **Response Quality** | LLM judge score for generated response | — | float 0–1 | Component |
| **Escalation Routing** | % human-review emails correctly flagged | — | float 0–1 | Component |
| **Avg Latency** | Mean execution time per email | — | milliseconds | Reported |
| **Success Rate** | % executions completed without error | — | float 0–1 | Reported |

### Composite Score Components

| Component | Weight | Source | Metric |
|---|---|---|---|
| Intent Accuracy | TBD % | `classify_intent` Lambda | Accuracy |
| Routing Accuracy | TBD % | Intent → INTENT_TO_ROUTE map | Accuracy |
| Confidence Calibration | TBD % | Confidence score quality | Calibration |
| Response Quality | TBD % | `claude_response` Lambda | LLM judge score |
| Escalation Routing | TBD % | `email_sender` Lambda | Agreement |

**Formula**:
```
Composite Score = weighted_avg(
  intent_accuracy,
  routing_accuracy,
  confidence_calibration,
  response_quality,
  escalation_routing
)
```

### Exit Codes

| Code | Condition | Meaning |
|---|---|---|
| 0 | composite_score ≥ 0.70 | PASS |
| 1 | composite_score < 0.70 | FAIL |
| 1 | execution errors | FAIL |
| 1 | unrecoverable error | FAIL |

### Per-Email Result Structure

| Field | Type | Definition | Example |
|---|---|---|---|
| email_id | string | Test email ID | laya_12345 |
| gold_intent | string | Ground truth intent | claim_status |
| predicted_intent | string | Pipeline prediction | claim_status |
| gold_route | string | Ground truth route | claims_team |
| predicted_route | string | Pipeline prediction | claims_team |
| confidence_score | float 0–1 | Model confidence | 0.92 |
| response_text | string | Generated response | "Your claim #... is being processed..." |
| action | string | Routing decision | auto_response / human_review / escalate |
| latency_ms | int | Execution time | 1245 |
| error | string or null | Error message if failed | null |

### Configuration

| Parameter | Value | Purpose |
|---|---|---|
| PASS_THRESHOLD | 0.70 | Composite score threshold |
| EXEC_TIMEOUT_SEC | 120 | Max wait per execution (seconds) |
| POLL_INTERVAL_SEC | 3 | Status poll frequency (seconds) |
| S3_PREFIX | test-pipeline | S3 key prefix for test emails |
| CONCURRENCY | 5–10 | Parallel Step Function executions |

---

## Summary: All Thresholds

| Task | Metric | Threshold | Pass Criterion |
|---|---|---|---|
| Intent Classification | Accuracy | ≥ 0.80 | accuracy >= 0.80 |
| RAG Retrieval | Hit Rate | ≥ 0.60 | hit_rate >= 0.60 |
| Response Generation | Escalation Agreement | ≥ 0.70 | agreement >= 0.70 |
| Claim Extraction | Overall Score | — | Reported (no threshold) |
| Pipeline E2E | Composite Score | ≥ 0.70 | composite >= 0.70 |

---

## Running Evaluations: Quick Command Reference

| Task | Command | Samples | Output File |
|---|---|---|---|
| Intent Classification | `python scripts/run_intent_eval.py --sample 50` | 50 | intent_eval_*.json |
| RAG Retrieval | `python scripts/run_rag_eval.py --sample 30` | 30 | rag_eval_*.json |
| Claim Extraction | `python scripts/run_claim_extraction_eval.py --limit 100` | 100 | claim_extraction_eval_*.json |
| Response Generation | `python scripts/run_response_eval.py` | From assessment | response_eval_*.json |
| Pipeline E2E | `python scripts/run_stepfn_assessment.py --sample 50` | 50 | stepfn_assessment_*.json |

---

## Test Dataset Source

| File | Records | Fields Used For |
|---|---|---|
| emails.jsonl | 1000 | Intent labels, email content |
| cases.jsonl | 1000 | Email ↔ Response mapping |
| draft_responses.jsonl | 1000 | Gold responses, doc groundings |
| claim_forms/claim_form_gold_dataset.jsonl | ~100 | Claim extraction gold fields |

---

## S3 Output Locations

| Metric | S3 Path | Latest Link |
|---|---|---|
| Intent Eval | s3://insuremail-ai-dev-logs/eval_reports/ | intent_eval_latest.json |
| RAG Eval | s3://insuremail-ai-dev-logs/eval_reports/ | rag_eval_latest.json |
| Response Eval | s3://insuremail-ai-dev-logs/eval_reports/ | response_eval_latest.json |
| Claim Extraction | s3://insuremail-ai-dev-logs/eval_reports/ | claim_extraction_eval_latest.json |
| Pipeline Assessment | s3://insuremail-ai-dev-logs/assessment/ | latest.json |
