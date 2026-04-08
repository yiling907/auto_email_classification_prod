# InsureMail AI — Feature List & AWS Cost Analysis

---

## Feature List

### 1. Email Ingestion

| Feature | Detail |
|---|---|
| **SES Email Receiving** | Inbound emails received via Amazon SES, stored raw in S3 |
| **Gmail IMAP Polling** | Scheduled Lambda polls Gmail inbox as an alternative ingestion source |
| **RFC 2822 Parsing** | Full MIME email parsing — headers, body (plain + HTML), threading |
| **PII Redaction** | Names, phone numbers, Irish PPS numbers, IBANs redacted before logging |
| **Attachment Extraction** | PDF → pypdf, DOCX → python-docx, TXT — text extracted and passed downstream |
| **Language Detection** | Detected language stored per email for routing decisions |

---

### 2. Intent Classification (`classify_intent_by_llm`)

| Feature | Detail |
|---|---|
| **17-Class Intent Model** | `coverage_query`, `claim_submission`, `claim_status`, `claim_reimbursement_query`, `pre_authorisation`, `payment_issue`, `policy_change`, `renewal_query`, `cancellation_request`, `enrollment_new_policy`, `dependent_addition`, `complaint`, `document_followup`, `hospital_network_query`, `id_verification`, `broker_query`, `other` |
| **ReAct Reasoning** | 5-step Thought/Action/Observation chain: identify intent → secondary intent → urgency/sentiment → routing → human review flag |
| **Secondary Intent Detection** | Detects co-present intents (e.g. `claim_status` + `payment_issue`) |
| **Multi-Dimension Output** | `customer_intent`, `secondary_intent`, `business_line`, `urgency`, `sentiment`, `route_team`, `gold_priority`, `requires_human_review` |
| **Route Team Mapping** | 12 route teams via `INTENT_TO_ROUTE` map (e.g. `claims_team`, `policy_renewals_team`, `complaints_team`) |
| **Accuracy Judge** | Second LLM pass evaluates classification quality across all fields including `reasoning_quality` |
| **Classification Reasoning Trace** | ReAct scratchpad stored in DynamoDB (`classification_reasoning`, truncated 1000 chars) |
| **BioBERT Fallback** | Alternative classifier using fine-tuned BioBERT for medical-domain emails |
| **Dual-Model Strategy** | Mistral 7B primary; Llama 3.1 8B as fallback; runtime-switchable via `ACTIVE_MODEL` env var |

---

### 3. Entity Extraction (`extract_entity`)

| Feature | Detail |
|---|---|
| **30+ Field Schema** | Member details, dependants, MRI, accidents, emergency dental, receipts, payment details |
| **Chain-of-Thought Extraction** | 8-section CoT walkthrough: each section of the claim form reasoned through before producing `FINAL_JSON` |
| **Textract Integration** | Scanned PDFs and images sent to Amazon Textract for OCR before extraction |
| **Claude Haiku Structured Extraction** | Bedrock Claude Haiku used for form field parsing from Textract output |
| **Model-Driven Confidence** | Extraction confidence (0.0–1.0) assessed by the model based on fields found; replaces hardcoded default |
| **Inline Fallback** | `FallbackEntities` Step Functions state returns empty entities on error — pipeline never hard-fails |

---

### 4. RAG Retrieval (`rag_retrieval`)

| Feature | Detail |
|---|---|
| **HyDE (Hypothetical Document Embeddings)** | Claude Haiku generates a hypothetical answer to the query; that answer is embedded for retrieval — improves recall over raw-query embedding |
| **Titan Embeddings V2** | 1024-dimensional normalized embeddings via `amazon.titan-embed-text-v2:0` |
| **BM25 Hybrid Search** | Sparse keyword matching combined with dense vector similarity |
| **RRF Fusion** | Reciprocal Rank Fusion merges BM25 and vector rankings into a unified candidate list |
| **Cross-Encoder Reranker** | ReAct-powered relevance judge: identify query topic → check snippet relevance → assign score + reason |
| **Knowledge Base Ingestion** | 500-token chunks, 50-token overlap, MD5 deduplication, parallel Titan embedding, DynamoDB storage |
| **SetEmptyRAG Fallback** | Returns empty context on retrieval error — downstream generation proceeds with CRM data only |

---

### 5. CRM Validation (`crm_validation`)

| Feature | Detail |
|---|---|
| **Text-to-SQL via ReAct** | 4-step chain: scan entities → scan email excerpt → select best identifier → assess confidence |
| **Identifier Priority Rule** | `customer_id` > `member_id` > `policy_number` > `email` — explicit selection reasoning in trace |
| **Customer & Policy Lookup** | Retrieves full customer profile + active policy details from DynamoDB `customers` table |
| **Eligibility Assessment** | Determines `eligible_for_intent` based on policy status, plan type, and requested service |
| **Short-Circuit Fast Path** | `_try_entities_shortcut()` bypasses LLM when entity extraction already provided a confident identifier |
| **SetEmptyCRM Fallback** | Returns empty CRM result on error — response generation applies "unverified customer" rules |

---

### 6. Response Generation (`llm_response` — generation pass)

| Feature | Detail |
|---|---|
| **Chain-of-Thought Drafting** | 5-step CoT: customer situation → CRM eligibility rule → knowledge base analysis → fraud check → response plan with citation mapping |
| **Numbered Citation System** | RAG documents presented as `[1] Title`, `[2] Title`, … — model places `[1]`, `[2]` superscripts after every cited fact |
| **Formal Citation Rules** | Every factual policy claim must be backed by a citation number; raw filenames and doc-IDs are forbidden |
| **CRM-Driven Branching** | Three strict rules: unverified → request ID; verified + ineligible → explain and guide; verified + eligible → full response |
| **Canonical Email Signature** | Always: `Best regards, / [Route Team] / Laya Healthcare` — enforced by post-processor |
| **Response Post-Processor** | `_clean_response()` strips Subject lines, raw filename citations, placeholder names, orphaned "refer to resources" phrases, and enforces canonical signature |
| **Generation Reasoning Trace** | Structured diagnostic trace stored in DynamoDB (`generation_reasoning`, 3000 chars): includes inputs (intent, body snippet, CRM summary, fraud score, RAG doc titles) + model CoT reasoning |

---

### 7. Response Evaluation (`llm_response` — evaluation pass)

| Feature | Detail |
|---|---|
| **8-Dimension Quality Judge** | `faithfulness`, `answer_relevance`, `context_precision`, `context_recall`, `completeness`, `helpfulness`, `safety_compliance`, `no_harmful_advice` |
| **ReAct Evaluation Chain** | One Thought/Action/Observation step per dimension — explicit per-dimension reasoning before final scores |
| **Confidence Calibration** | Weighted average of all 8 scores (configurable `EVAL_WEIGHTS`) → single `confidence_score` (0–1) |
| **Confidence-Based Routing** | `≥ 0.80` → auto-send; `0.50–0.79` → human review queue; `< 0.50` → escalate |
| **Metrics Storage** | Latency, cost, and all 8 eval scores stored to `model_metrics` DynamoDB table per email |

---

### 8. Email Sending (`email_sender`)

| Feature | Detail |
|---|---|
| **Knowledge Base Attachments** | Source files referenced in the response are fetched from S3 and attached automatically |
| **Citation Hyperlinks** | `[1]`, `[2]` in the HTML email body become `<sup><a href="cid:kb-attachment-1">` links pointing to the corresponding attached file |
| **Footnote Reference Bar** | Attached references listed at the bottom of the email with `cid:` links: `[1] Renewal Policy Guide  [2] Laya App Renewal` |
| **Attachment Deduplication** | Multiple RAG chunks from the same source file produce a single attachment |
| **Size Guard** | Per-file limit: 4 MB; total limit: 8 MB (SES 10 MB raw message cap) — oversized files skipped with log warning |
| **MIME Raw Email** | Uses `send_raw_email` with `Content-ID` headers when attachments present; falls back to `send_email` for plain responses |
| **DynamoDB Status Update** | `email_sent`, `email_message_id`, `email_sent_timestamp`, `attachment_count` stored on email record |

---

### 9. Reasoning & Traceability

| Feature | Detail |
|---|---|
| **`reasoning_utils.py` Shared Module** | Centralised prompt scaffolds (`REACT_SYSTEM_PREFIX`, `COT_SYSTEM_PREFIX`) and parsers (`extract_react_answer`, `extract_cot_answer`, `extract_json_block`) used by all 5 LLM Lambdas |
| **Structured CloudWatch Logging** | `log_reasoning_trace()` emits one JSON line per LLM call: `trace_id`, `lambda`, `reasoning_chain`, `final_answer`, `reasoning_format_valid` |
| **`reasoning_format_valid` Flag** | Boolean in every CloudWatch log entry — alarm-ready metric for monitoring prompt compliance rate |
| **DynamoDB Reasoning Storage** | `classification_reasoning` (1000 chars) and `generation_reasoning` (3000 chars) stored on the email record for dashboard review |
| **Backward-Compatible Fallbacks** | All 5 Lambdas fall back to JSON extraction from raw output when model omits reasoning format |

---

### 10. Dashboard (`api_handlers` + React frontend)

| Feature | Detail |
|---|---|
| **Email List View** | Paginated, newest-first; filter by status, confidence level, intent |
| **Email Detail View** | Full metadata, classification results, extracted entities, AI decision, generated response |
| **Classification Reasoning Trace** | Collapsible ReAct trace panel showing step-by-step intent classification reasoning |
| **Generation Reasoning Trace** | Collapsible CoT trace showing inputs (CRM, RAG docs, fraud score) + model reasoning |
| **Editable Response** | Agent can edit the AI-generated response before sending; unsaved changes indicator |
| **Save Draft** | Agent saves edited response to DynamoDB without sending |
| **Send to Customer** | Agent-initiated send via dashboard; triggers `email_sender` Lambda with full attachment pipeline |
| **Model Metrics Page** | Per-field accuracy, latency, cost, and eval scores by model and task type |
| **`reasoning_quality` Metric** | Dashboard tracks whether the model's reasoning chain supports its final classification answer |

---

### 11. Pipeline Orchestration

| Feature | Detail |
|---|---|
| **Step Functions Workflow** | 6-step DAG: `email_parser` → `[classify_intent ∥ extract_entities]` → `rag_retrieval` → `crm_validation` → `llm_response` → `email_sender` |
| **Parallel Classification + Extraction** | Intent classification and entity extraction run concurrently to reduce end-to-end latency |
| **Graceful Fallbacks at Every Step** | `FallbackEntities`, `SetEmptyRAG`, `SetEmptyCRM` states ensure pipeline never hard-fails mid-run |
| **`reference_ids` Passthrough** | RAG document IDs flow from `llm_response` → Step Functions state → `email_sender` for attachment resolution |
| **`save_result` Lambda** | Final pipeline execution trace (action taken, confidence, all step outputs) persisted to `pipeline_results` table |

---

### 12. Infrastructure

| Feature | Detail |
|---|---|
| **Full Terraform IaC** | All 13 Lambda functions, 5 DynamoDB tables, Step Functions, API Gateway, SES, S3, CloudWatch, IAM — fully managed |
| **`PAY_PER_REQUEST` DynamoDB** | No provisioned capacity — scales to zero, scales to enterprise automatically |
| **CloudFront + S3 Frontend** | React dashboard built with Vite, deployed to S3, served via CloudFront |
| **EventBridge Monitoring** | Automated rules trigger on pipeline failures and SES bounce/complaint events |
| **SageMaker Inference Endpoint** | GPU PyTorch endpoint for custom ML model serving (e.g. BioBERT at scale) |

---

## AWS Cost Analysis — March 2026

**Emails processed:** 934 executions (426 succeeded, 508 failed)

### Pipeline-Relevant Costs (March 2026)

| Service | Cost (USD) | Notes |
|---|---|---|
| Amazon Bedrock (Mistral/Llama/Titan) | $1.1917 | Intent, RAG, response generation |
| Amazon DynamoDB | $0.3837 | 5 tables, reads/writes per email |
| AWS Step Functions | $0.0809 | 6 state transitions × 934 executions |
| Amazon S3 | $0.0485 | Email storage, knowledge-base, logs |
| AWS Secrets Manager | $0.0092 | Secret reads per invocation |
| Amazon API Gateway | $0.0091 | Dashboard REST API calls |
| Amazon SES | $0.0024 | Outbound email responses |
| AWS Lambda | $0.00 | Within free tier (40K+ invocations) |
| Amazon Textract | $0.00 | Within free tier (17 pages) |
| Amazon CloudWatch | $0.0006 | Logs & metrics |
| AWS KMS | $0.0013 | Encryption |
| **Total** | **~$1.73** | |

> **Excluded from pipeline cost:** Claude Sonnet 4.5 ($58.52), Claude Haiku ($1.48) — these are billed separately and appear unrelated to the InsureMail pipeline (likely from other workloads or Claude Code usage on this account). EC2, EKS, ELB are also unrelated to this project.

---

### Cost Per 1,000 Emails

```
$1.73 / 934 emails = $0.00185 per email
$0.00185 × 1,000   = ~$1.85 per 1,000 emails
```

| Breakdown | Cost per 1K emails |
|---|---|
| Bedrock (AI inference) | $1.28 |
| DynamoDB | $0.41 |
| Step Functions | $0.09 |
| S3 + SES + Other | $0.07 |
| **Total** | **~$1.85** |

---

### Azure Equivalent Resources

| AWS Resource | Function | Azure Equivalent | Cost Model |
|---|---|---|---|
| Amazon Bedrock (Mistral/Llama/Titan) | Intent classification, RAG embeddings, response generation | Azure AI Foundry (Mistral & Llama via Model Catalog + text-embedding-3-small) | Per 1K tokens: ~$0.0002 input / $0.0006 output (Mistral); embeddings ~$0.00002/1K tokens |
| Amazon DynamoDB | 5 tables for emails, metrics, embeddings, customers, pipeline results | Azure Cosmos DB (NoSQL API) | PAY_PER_REQUEST: ~$0.25/1M RU reads, ~$1.25/1M RU writes |
| AWS Step Functions | 6-step email processing workflow orchestration | Azure Durable Functions / Logic Apps | Durable Functions billed like Azure Functions; Logic Apps ~$0.000025/action |
| Amazon S3 | Raw emails, knowledge-base docs, logs, frontend static assets | Azure Blob Storage | ~$0.018/GB/month + $0.004/10K operations |
| AWS Secrets Manager | Secure storage of API keys and credentials | Azure Key Vault | ~$0.03/10K operations; secrets ~$0.60/secret/month |
| Amazon API Gateway | REST API (7 endpoints) for React dashboard | Azure API Management (APIM) | Consumption tier: ~$3.50/1M calls |
| Amazon SES | Outbound email sending with attachments, bounce/complaint handling | Azure Communication Services (Email) | ~$0.00025/email sent |
| AWS Lambda | 13 serverless pipeline handler functions | Azure Functions | Pay-per-execution; first 1M requests/month free |
| Amazon Textract | Extract text from PDF/image attachments | Azure AI Document Intelligence | ~$1.50/1K pages; first 500 pages/month free |
| Amazon CloudWatch | Lambda logs, alarms, pipeline dashboards | Azure Monitor + Log Analytics Workspace | ~$2.30/GB ingested; first 5 GB/month free |
| AWS KMS | Encryption key management for S3, DynamoDB | Azure Key Vault (Keys) | ~$0.03/10K operations; RSA keys ~$1/key/month |

---

### Key Observations

- **Bedrock is the dominant cost** (~70%), driven by Mistral 7B calls across 5 pipeline steps per email.
- **Lambda is effectively free** at this scale (within the 1M free-tier requests/month).
- The **508 failed executions** still incur partial costs (Step Functions transitions, Lambda invocations) — fixing failure rate could reduce costs ~30%.

---

### Future Enterprise Resources (Available in Account)

| AWS Resource | Already in Account | How to Use for InsureMail Enterprise |
|---|---|---|
| **AWS X-Ray** | Active (472 traces/month, $0) | Distributed tracing across all 6 pipeline steps — visualize bottlenecks, debug failures end-to-end |
| **Amazon Rekognition** | Active ($0.004 billed) | Scan email attachments for identity documents (driver's license, insurance card) — feeds into `id_verification` intent |
| **Amazon Comprehend Medical** | Active (72 calls, $0) | Extract medical entities (diagnoses, medications, procedures) from claims emails — enriches `extract_entity` Lambda |
| **Amazon Nova Pro / Lite / Micro** | Available on Bedrock | Upgrade from Mistral 7B — Nova Pro for complex claims reasoning, Nova Micro as cheaper fallback |
| **Amazon Nova Sonic** | Available on Bedrock | Voice-to-email: transcribe customer phone calls → process through pipeline |
| **Amazon Nova Multimodal Embeddings** | Available on Bedrock | Replace Titan Embeddings — supports image+text RAG (useful for scanned claim forms) |
| **Llama 3 70B** | Available on Bedrock | Higher-accuracy response generation for complex escalation cases vs current 8B |
| **Claude 3.5 Sonnet / Haiku** | Active on Bedrock ($60 billed) | Already used on account — can replace Mistral for intent classification with better accuracy |
| **Amazon SQS** | Available ($0) | Decouple email ingestion from pipeline — buffer bursts, enable retry queues for failed executions |
| **Amazon SNS** | Available ($0) | Push notifications to agents when emails are escalated to human review |
| **AWS Glue** | Active ($0) | ETL pipeline for model metrics → data warehouse for analytics and compliance reporting |
| **Amazon EKS** | Active cluster in account | Host BioBERT or custom ML models at scale instead of SageMaker (lower cost at high volume) |
| **Amazon ECR** | Active repo in account | Containerize Lambda functions → deploy as EKS workloads for GPU-heavy inference |

**Top 3 highest-impact picks for enterprise:**
1. **SQS** — adds resilience and burst handling (critical for enterprise email volume)
2. **Comprehend Medical** — directly adds value for health insurance claims extraction
3. **X-Ray** — required for enterprise SLA monitoring and audit trails
