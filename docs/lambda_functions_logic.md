# InsureMail AI — All Lambda Functions Logic

---

## Pipeline Overview

```
EventBridge (schedule)
        │
        ▼
gmail_imap_poller ──► S3 (.eml) ──► Step Functions state machine
                                            │
                            ┌───────────────┼───────────────────┐
                            ▼               ▼                   │
                      email_parser    [Parallel branch]         │
                            │         classify_intent           │
                            │         extract_entity            │
                            └───────────────┤                   │
                                            ▼                   │
                                      rag_retrieval             │
                                            ▼                   │
                                      crm_validation            │
                                            ▼                   │
                                      claude_response           │
                                            ▼                   │
                                       email_sender             │
                                            ▼                   │
                                        save_result ◄───────────┘

Side paths (not in Step Functions):
  rag_ingestion       — offline document ingestion (S3 trigger)
  api_handlers        — REST API for React dashboard
  sagemaker_inference — POST /api/model/inference proxy
```

---

## 1. `gmail_imap_poller`

**Trigger:** EventBridge scheduled rule. Ignores `event` and `context`.

### Flow

```
1. connect_to_gmail()
        Opens IMAP4_SSL (port 993 TLS) to imap.gmail.com
        Authenticates with GMAIL_APP_PASSWORD (Google App Password)
        Returns authenticated mail object — or raises on failure

2. mail.select('inbox')

3. mail.search(None, 'UNSEEN')
        Returns space-separated message sequence numbers for unread emails
        Empty list → return {emails_processed: 0, errors: []}

4. For each email_id:
        a. mail.fetch(email_id, '(RFC822)')       ← full raw RFC 2822 bytes
           status != 'OK' → log warning, continue

        b. email.message_from_bytes(raw_email)    ← parse into Message object

        c. process_email(email_message, raw_email)
              ├─ Extract from_addr, to_addr, subject, message_id
              ├─ Generate internal email_id (UUID)
              ├─ s3_client.put_object → incoming/gmail-{uuid}.eml
              │       Metadata: from, to, subject, source=gmail-imap
              └─ stepfunctions_client.start_execution
                     Input shape: SNS-compatible envelope
                     { Records[0].Sns.Message: { notificationType, mail, receipt.action.objectKey } }
                     SNS envelope is used so email_parser handles both SES and Gmail identically

        d. If success + MARK_AS_READ:
              mail.store(email_id, '+FLAGS', '\\Seen')

        e. If failure: append to errors[], continue (never aborts batch)

5. mail.close() + mail.logout()
6. Return { statusCode:200, emails_processed, errors, timestamp }
```

### Error Isolation

| Scope | On failure |
|---|---|
| Per-email (inner `try`) | Append to `errors[]`, continue loop |
| IMAP session (outer `try`) | Return `statusCode: 500` |

### Configuration

| Env var | Required | Default | Description |
|---|---|---|---|
| `GMAIL_ADDRESS` | Yes | — | Gmail account to poll |
| `GMAIL_APP_PASSWORD` | Yes | — | Google App Password (not real password) |
| `S3_BUCKET` | Yes | — | Bucket for raw `.eml` storage |
| `STATE_MACHINE_ARN` | Yes | — | Step Functions state machine to trigger |
| `IMAP_SERVER` | No | `imap.gmail.com` | Override for non-Gmail providers |
| `MARK_AS_READ` | No | `true` | Flag processed emails `\Seen` to prevent reprocessing |

---

## 2. `email_parser`

**Trigger:** Step Functions (first step in the state machine). Accepts S3 events, SES/SNS events, or direct `{bucket, key}` payloads.

### Event Routing

```
event has 'Records'?
  ├─ record['s3'] present   → bucket + key from S3 event
  └─ record['Sns'] present  → parse SNS Message JSON → receipt.action.bucketName/objectKey
else
  → bucket/key directly from event dict
```

### Flow

```
1. s3_client.get_object(Bucket, Key)
        Downloads raw RFC 2822 email as UTF-8 string

2. parse_email(raw_email)
        ├─ parseaddr(From)          → sender_name, sender_email
        ├─ parseaddr(To)            → to_address
        ├─ _parse_date(Date)        → ISO 8601 UTC timestamp
        ├─ _extract_thread_id()     → References header → first Message-ID → uuid fallback
        ├─ _extract_message_index() → count of References + 1
        ├─ _extract_bodies()        → walks MIME tree
        │       multipart: collects first text/plain + first text/html, skips attachments
        │       single part: decodes payload directly
        ├─ _count_attachments()     → counts parts with Content-Disposition: attachment
        ├─ _extract_policy_number() → regex POL-IE-\d{6}
        ├─ _extract_member_id()     → regex MEM-\d{6}
        ├─ _detect_pii()            → email / Irish phone / PPSN patterns
        └─ _detect_medical_terms()  → set membership check against 30 medical terms

3. Generate email_id (UUID)
        Add: email_id, s3_bucket, s3_key, processing_status='parsed'

4. _dynamo_safe(parsed_data)
        Recursively converts float → Decimal for DynamoDB compatibility

5. email_table.put_item(Item=safe_data)
        Stores the full parsed record in the email_processing DynamoDB table

6. Return { statusCode:200, email_id, parsed_data }
```

### Key Regex Patterns

| Pattern | Matches |
|---|---|
| `POL-IE-\d{6}` | Policy numbers |
| `MEM-\d{6}` | Member IDs |
| `\b\d{7}[A-Z]{1,2}\b` | Irish PPS numbers |
| `(\+353\|0)\d[\d\s\-]{7,11}` | Irish phone numbers |

### Medical Terms Detection

Checks 30 terms including: `hospital`, `clinic`, `gp`, `doctor`, `mri`, `x-ray`, `ct scan`, `pre-authorisation`, `cardiac`, `oncology`, `maternity`, `physiotherapy`, and more.

---

## 3. `classify_intent`

**Trigger:** Step Functions (parallel branch alongside `extract_entity`).

### Model Registry

| Key | Bedrock model ID | Role |
|---|---|---|
| `mistral-7b` | `mistral.mistral-7b-instruct-v0:2` | Primary (default) |
| `llama-3.1-8b` | `meta.llama3-8b-instruct-v1:0` | Alternate / judge |

`ACTIVE_MODEL` env var (default `mistral-7b`) selects the classifier; the other model acts as accuracy judge.

### Flow

```
1. classify_email(email_id, subject, body, active_model)
        ├─ Build _CLASSIFICATION_PROMPT with subject, body, 17 valid intents, 12 route teams
        ├─ _invoke_model() → Bedrock (Mistral or Meta request format)
        ├─ _parse_classification(raw_output)
        │       _extract_json(): find first {...} in output (handles preamble + markdown fences)
        │       Validate each field against enums:
        │         customer_intent   → 17 valid values (fallback: 'other')
        │         secondary_intent  → same 17 values (fallback: '')
        │         urgency           → low|medium|high (fallback: 'low')
        │         sentiment         → positive|neutral|frustrated|upset (fallback: 'neutral')
        │         gold_route_team   → 12 valid teams; if invalid → INTENT_TO_ROUTE[intent]
        │         gold_priority     → normal|high|urgent (fallback: 'normal')
        │         requires_human_review → forced True for complaint/pre_authorisation/urgent
        └─ _store_metrics() → model_metrics DynamoDB table

2. _update_email_record(email_id, classification)
        UpdateExpression sets 7 classification fields + classification_timestamp

3. evaluate_accuracy(email_id, subject, body, classification, judge_model)
        ├─ Build _ACCURACY_PROMPT with the 7-field classification JSON
        ├─ _invoke_model() → judge model
        ├─ _parse_accuracy() → {field: 0|1} binary scores for all 7 fields
        ├─ overall_score = mean(per_field values)
        └─ _store_metrics() → model_metrics table

4. Return { statusCode, email_id, active_model, classification, metrics, accuracy_evaluation }
```

### INTENT_TO_ROUTE Mapping (17 intents → 12 teams)

| Intent | Route team |
|---|---|
| `claim_submission`, `claim_status`, `claim_reimbursement_query` | `claims_team` |
| `pre_authorisation` | `medical_review_team` |
| `payment_issue` | `finance_support_team` |
| `policy_change`, `dependent_addition` | `policy_admin_team` |
| `renewal_query` | `renewals_team` |
| `cancellation_request` | `retention_team` |
| `enrollment_new_policy` | `sales_enrollment_team` |
| `complaint` | `complaints_team` |
| `document_followup`, `id_verification` | `operations_team` |
| `hospital_network_query` | `provider_support_team` |
| `coverage_query` | `customer_support_team` |
| `broker_query`, `other` | `general_support_team` |

---

## 4. `extract_entity`

**Trigger:** Step Functions (parallel branch alongside `classify_intent`).

### Flow

```
1. Seed base_entities from email_parser output
        policy_number, member_id, customer_id, sender_email, pii_present

2. If has_attachment=True:
        _run_textract_on_email(bucket, key, email_id)
          ├─ s3.get_object → raw MIME bytes
          ├─ Walk MIME parts (accepts both 'attachment' and 'inline' dispositions)
          ├─ Per attachment:
          │     PDF  → _extract_pdf_text()
          │               Step 1: pypdf text-layer extraction (fast, zero cost)
          │                       Works for text-layer PDFs (Word exports, ReportLab, etc.)
          │               Step 2: if pypdf returns empty (scanned/image PDF) →
          │                       Upload to temp S3 key →
          │                       textract.detect_document_text(S3Object=temp_key) →
          │                       Delete temp key in finally block
          │                       (PDFs require S3Object mode; Bytes mode is image-only)
          │                       Skip if > 5 MB (Textract sync API limit)
          │     Image (JPEG/PNG/TIFF) → _textract_image_bytes()
          │               textract.detect_document_text(Bytes=payload)
          │               Skip if > 5 MB
          └─ Returns list of "[PDF: filename]\n{text}" chunks

3. _extract_via_bedrock(subject, email_body, text_chunks, email_id)
        ├─ Build _EXTRACTION_PROMPT
        │     8 sections mirroring the Laya Healthcare Out-patient Claim Form:
        │       §1 Member details     §2 Dependants      §3 MRI
        │       §4 Accidents          §5 Emergency Dental §6 Receipts
        │       §7 Payment details    §8 Meta/confidence
        │     Combine up to first 3 attachment chunks, truncate to 8000 chars
        ├─ bedrock.invoke_model(Claude 3 Haiku, max_tokens=2048, temperature=0)
        ├─ _parse_extraction_json(text_out)
        │     regex find first {...} block
        │     Pop 'confidence' field (0–1, clamped)
        │     Strip null/empty scalar values; keep arrays + booleans
        └─ Return (extracted_fields, confidence, bedrock_used=True)

4. Promote identifiers
        If email_parser didn't find policy_number/member_id/customer_id
        but Bedrock did → move them into base_entities (avoids duplication)

5. Return {
        policy_number, member_id, customer_id, sender_email, pii_present,
        extracted_fields (full Laya claim form fields dict),
        textract_used, bedrock_used, extraction_confidence, sources
   }
```

### Extracted Fields Schema (§1–§8)

`membership_no`, `title`, `surname`, `forenames`, `date_of_birth`, `telephone`, `correspondence_address`, `dependants[]`, `mri_date`, `mri_reason_for_referral`, `mri_centre`, `mri_procedure`, `mri_referring_gp`, `mri_consultant_code`, `accident_date`, `accident_description`, `expenses_recoverable`, `recovery_via_solicitor`, `recovery_via_piab`, `third_party_details`, `dental_injury_date`, `dental_injury_place`, `dental_injury_description`, `dental_treatment_start`, `dental_treatment_end`, `dental_cost`, `receipts[]`, `receipts_total_cost`, `account_holder_name`, `account_number`, `bank_sort_code`, `bank_name_address`, `declaration_date`, `doc_category`

---

## 5. `rag_retrieval`

**Trigger:** Step Functions (sequential, after the parallel branch completes).

### Algorithm: HyDE → Embed → BM25 → RRF → Rerank

```
1. _preprocess(email_text, intent)
        Strip greeting regex (Dear …, Hi …, Hello …)
        Strip sign-off regex (Kind regards …, Best regards …, Thank you …)
        Prepend "Insurance query about {intent}: " if intent present
        Truncate to 8000 chars

2. _hyde_expand(clean_query)   [Hypothetical Document Embedding]
        Prompt Claude 3 Haiku:
          "Write a 2-3 sentence factual answer as it would appear in Laya Healthcare docs"
        Embeds the ANSWER, not the question
        → lands in the same embedding space as real KB documents
        Fallback: return raw query if Haiku call fails

3. _embed(hyde_doc)
        Titan Embeddings V2 → 1024-dim normalized vector
        Truncate input to 8000 chars

4. _scan_all()
        Paginated DynamoDB Scan of kb_embeddings table
        Follows LastEvaluatedKey until table fully loaded

5. Score all documents
        vec_scores[i]  = cosine_similarity(query_vec, doc_embedding[i])
        bm25_scores[i] = BM25.score(clean_query, i)

        BM25 implementation:
          IDF = log((N - df + 0.5) / (df + 0.5) + 1)
          TF normalization: k1=1.5, b=0.75, avgdl=mean doc length

6. _rrf_fuse(vec_scores, bm25_scores, k=60)
        Reciprocal Rank Fusion:
          rrf[i] += 1 / (60 + vec_rank[i] + 1)
          rrf[i] += 1 / (60 + bm25_rank[i] + 1)
        Sort descending by combined rrf score

7. Pre-filter
        Take top 12 candidates from RRF
        Drop any with vec_score < 0.25

8. _cross_encoder_rerank(query, candidates)   [6 parallel Haiku workers]
        For each candidate, Claude 3 Haiku scores (query, doc) pair jointly:
          "Rate relevance 0-10" → JSON {"score": N}
        Fallback on failure: rrf_score × 5

        final_score = 0.5 × reranker + 0.3 × vec_score + 0.2 × rrf_score

9. Return top_k docs sorted by final_score
        { doc_id, doc_type, content, similarity_score, metadata }
```

---

## 6. `crm_validation`

**Trigger:** Step Functions (sequential, after `rag_retrieval`).

### Flow

```
1. _try_entities_shortcut(extracted_entities)
        Check entities from email_parser in priority order:
          customer_id > member_id > policy_number > email
        Validate each against strict regex whitelist (_sanitise)
        If found: skip Bedrock model call entirely (faster + cheaper)

2. If no shortcut found: _build_query_plan()
        Text-to-SQL via Mistral 7B on Bedrock:
          Prompt includes: table schema, intent, extracted entities, email excerpt (400 chars)
          Request format: <s>[INST] {prompt} [/INST]
          temperature=0 (deterministic), max_tokens=128
        Parse response JSON: { lookup_field, lookup_value, confidence }

3. _sanitise(field, value)
        Whitelist check: field must be in {customer_id, member_id, policy_number, email}
        Regex match per field:
          customer_id   → ^CUST-\d{6}$
          member_id     → ^MEM-\d{6}$
          policy_number → ^POL-IE-\d{6}$
          email         → standard email regex
        Both field AND value must pass — model output never touches DynamoDB raw

4. _execute_query(field, value)
        customer_id  → GetItem on PK  (O(1), exact match)
        anything else → Scan + FilterExpression(Attr(field).eq(value))
                        No Limit= — DynamoDB Limit caps items read, not items matched

5. _derive_policy_status(record)
        Compare policy_start_date and renewal_date to today:
          pending  → start_date > today
          expired  → renewal_date < today
          active   → start_date ≤ today ≤ renewal_date
        days_to_renewal = (renewal_date - today).days
        renewal_required = True when days_to_renewal < 30

6. _validate_for_intent(lifecycle, intent, plan_name)
        Intents in _INTENT_REQUIRES_ACTIVE need an active policy:
          claim_submission, claim_status, claim_reimbursement_query,
          pre_authorisation, coverage_query, payment_issue,
          policy_change, dependent_addition, hospital_network_query
        If policy not active → eligible=False + descriptive reason message
        Other intents (renewal_query, complaint, etc.) → always eligible=True

7. _redact_pii(record)
        email → ***@domain.com   (keeps domain for debugging)
        phone → ***{last 3 digits}
        dob   → [REDACTED]

8. Return crm_context = {
        crm_found: bool,
        customer: { customer_id, member_id, full_name, email(masked), phone(masked),
                    county, address, preferred_language, family_status, member_count },
        policy:   { policy_number, plan_name, policy_status, policy_active,
                    policy_start_date, renewal_date, days_to_renewal, renewal_required,
                    payment_method, currency, annual_limit_eur, daily_rate_eur },
        validation: { intent, policy_exists, eligible_for_intent, ineligibility_reason },
        query_audit: { model_used, lookup_field, lookup_value, model_confidence,
                       latency_ms, shortcut_used }
   }
```

### Plan Coverage Lookup (hardcoded for Laya Ireland)

| Plan | Annual limit | Daily rate |
|---|---|---|
| Essential Care | €50,000 | €100 |
| Everyday Care | €75,000 | €150 |
| Select Hospital | €100,000 | €200 |
| HealthWise Gold | €150,000 | €250 |
| Family Plus | €200,000 | €300 |
| Corporate Flex | €250,000 | €350 |

---

## 7. `claude_response`

**Trigger:** Step Functions (sequential, after `crm_validation`).

### Flow

```
1. generate_response(active_model)
        ├─ Format _GENERATION_PROMPT:
        │     customer email (subject + body)
        │     customer_intent from classify_intent output
        │     crm_validation JSON (controls what the agent may reveal)
        │     fraud_score JSON
        │     RAG context: top 5 docs, 600 chars each, numbered by doc_id
        │
        │     CRM rules enforced in prompt:
        │       crm_found=False        → ask for member ID / policy number, no account details
        │       crm_found + ineligible → explain reason (e.g. policy expired) + guide next steps
        │       crm_found + eligible   → full response using verified plan details
        │
        ├─ _invoke_model() → Bedrock (Mistral or Meta format, max_tokens=2048)
        ├─ _extract_json() → find first {...} in output (handles preamble + markdown fences)
        ├─ Parse { response_text, reference_ids }
        └─ _store_metrics(generation metrics) → model_metrics table

2. _update_email_response(email_id, response_text, reference_ids)
        SET llm_response + reference_ids on the email_processing record

3. evaluate_response(judge_model)   [8-dimension RAG evaluation]
        ├─ Format _EVALUATION_PROMPT with question, rag_context, crm, fraud, response
        ├─ _invoke_model() → judge model
        ├─ _parse_eval_scores() → {dimension: float 0–1}, default 0.5 on missing fields
        └─ _calculate_confidence(scores, rag_docs)
              eval_score = Σ(EVAL_WEIGHTS[k] × scores[k])   ← weighted sum
              rag_score  = mean(doc.similarity_score for all retrieved docs)
              confidence = 0.5 × eval_score + 0.5 × rag_score

4. Routing decision from confidence:
        ≥ 0.8  → action='auto_response', confidence_level='high'
        ≥ 0.5  → action='human_review',  confidence_level='medium'
        < 0.5  → action='escalate',      confidence_level='low'

5. _update_confidence(email_id, confidence, confidence_level, action)
        SET confidence_score, confidence_level, action, processing_status='completed', response_timestamp

6. Return { statusCode, email_id, response_text, reference_ids,
            confidence_score, confidence_level, action, evaluation }
```

### Evaluation Dimension Weights

| Dimension | Weight | Rationale |
|---|---|---|
| `faithfulness` | 0.25 | No hallucination — critical for insurance |
| `answer_relevance` | 0.20 | Directly answers the customer's question |
| `safety_compliance` | 0.20 | Legally safe and regulatory compliant |
| `no_harmful_advice` | 0.15 | Avoids misleading or incorrect guidance |
| `completeness` | 0.10 | Covers all key points raised |
| `helpfulness` | 0.05 | Clear and actionable |
| `context_precision` | 0.025 | Retrieved chunks are relevant |
| `context_recall` | 0.025 | Context covers what is needed |

---

## 8. `email_sender`

**Trigger:** Step Functions (after `claude_response`).

### Flow

```
1. Validate: recipient_email and response_text must both be present

2. Build subject: "Re: {original_subject}"

3. build_email_body(response_text, confidence_score)
        Returns HTML email with:
          Header:     purple (#667eea) banner — "InsureMail AI Support"
          Content:    response_text (newlines → <br>)
          Badge:      confidence score — green (#28a745) if ≥ 0.8, yellow (#ffc107) otherwise
          Footer:     automated-response disclaimer + copyright

4. ses_client.send_email(Source, Destination, Subject, Body{Text+Html})
        Sends both plain text and HTML MIME parts

5. If email_id present:
        email_table.update_item
          SET email_sent=True, email_message_id, email_sent_timestamp

6. Return { statusCode:200, email_sent:True, message_id, recipient }

SES error handling:
  MessageRejected                    → SES sending limits / recipient not verified
  MailFromDomainNotVerifiedException → sender domain not verified in SES
```

---

## 9. `save_result`

**Trigger:** Step Functions (final step after `email_sender`). Never raises — always returns success to keep the workflow alive.

### Flow

```
1. Determine email_id
        event.parsed_email.email_id (fallback: 'unknown')

2. Determine final_action
        email_result.email_sent = True   → 'auto_response'
        final_action_obj present         → final_action_obj.action
        neither                          → 'auto_response' (AutoRespond Catch path)

3. Serialize entire Step Functions input state
        json.dumps(event, default=str)   ← full pipeline state as JSON string

4. dynamodb.Table(PIPELINE_RESULTS_TABLE_NAME).put_item({
        email_id:         ← partition key
        final_action:     ← GSI partition key
        executed_at:      ← GSI sort key (ISO 8601 UTC)
        input:            ← full state JSON string (audit + analytics)
        pipeline_version: "1.0"
   })

5. On any exception:
        Log error, return { saved:False, error }
        Never raises — Step Functions execution always reaches Success state
```

---

## 10. `rag_ingestion`

**Trigger:** S3 event (document uploaded to KB bucket) or direct `{bucket, key}` invocation.

### Flow

```
1. s3_client.get_object → raw bytes
        .pdf extension → pypdf.PdfReader → extract text from all pages joined with \n
        other           → UTF-8 decode

2. determine_doc_type(key)
        Keyword in S3 key path:
          policy       → 'policy'
          claim        → 'claims_guideline'
          compliance / disclaimer → 'compliance'
          faq          → 'faq'
          template     → 'template'
          else         → 'general'

3. chunk_document(text)   [sentence-aware chunking]
        Split on sentence boundaries: regex (?<=[.!?])\s+
        CHUNK_SIZE = 500 words, OVERLAP = 50 words, MIN_CHUNK_WORDS = 20

        Algorithm:
          for each sentence:
            if sentence > CHUNK_SIZE:
              hard-split across multiple chunks (fill current, keep OVERLAP tail)
            if current + sentence > CHUNK_SIZE:
              flush current chunk, keep last OVERLAP words
            append sentence words to current buffer
          flush remaining buffer

        _maybe_add_chunk():
          skip if < 20 words
          MD5-deduplicate identical chunks (cross-file dedup)

4. embed_chunks_parallel(chunks, source_key, doc_type)   [8 concurrent Bedrock workers]
        For each chunk:
          doc_id = "{s3_key_with_slashes_replaced}_{chunk_index}"
          generate_embedding(chunk)
            → Titan Embeddings V2, 1024-dim, normalized
            → Truncate input to 8000 chars

5. batch_store_embeddings(results)
        embeddings_table.batch_writer() — auto-batches in groups of 25
        Each DynamoDB item:
          doc_id, doc_type, content, embedding (JSON string),
          metadata { source_key, chunk_index, content_length, embedding_dim },
          timestamp

6. Return { statusCode, document, doc_type, chunks_processed, total_chunks }
```

---

## 11. `api_handlers`

**Trigger:** API Gateway (dashboard REST API). Routes on `path` + `httpMethod`.

### Route Table

| Method | Path | Handler | Description |
|---|---|---|---|
| GET | `/api/dashboard/overview` | `get_dashboard_overview()` | Total emails, confidence distribution, auto-response rate, last 10 emails |
| GET | `/api/emails` | `get_emails_list()` | Paginated scan with optional `confidence_level`, `action`, `processing_status` filters |
| GET | `/api/email/{id}` | `get_email_detail()` | GetItem by `email_id` |
| POST | `/api/email/{id}` | `update_email_response_text()` | Edit `llm_response` field on email record |
| POST | `/api/email/{id}/send` | `send_email_response()` | Invoke `email_sender` Lambda synchronously |
| GET | `/api/metrics/models` | `get_model_metrics()` | Aggregate by task_type and model_name; includes per-field accuracy + eval scores |
| GET | `/api/metrics/rag` | `get_rag_metrics()` | Total chunks, source files, chunks-per-file (paginated scan) |
| GET | `/api/metrics/evaluations` | `get_evaluations()` | Reference eval report from S3 + Claude eval records from model_metrics |
| GET | `/api/assessment` | `get_assessment()` | Latest assessment JSON from S3 `assessment/latest.json` |
| POST | `/api/assessment/run` | `run_assessment()` | Fire-and-forget async Lambda invoke |
| GET | `/api/settings` | `get_settings()` | Read `ACTIVE_MODEL` env var from classify_intent + claude_response Lambdas |
| POST | `/api/settings` | `update_settings()` | Patch `ACTIVE_MODEL` on managed Lambda function configurations |

### Shared Behaviours

- `DecimalEncoder` converts DynamoDB `Decimal` → `float` in all JSON responses
- All responses append `Access-Control-Allow-Origin: *` CORS headers
- `get_rag_metrics()` uses a paginated scan loop — embedding vectors (1024 floats each) hit the 1 MB DynamoDB page limit quickly
- `update_settings()` validates model against `{'mistral-7b', 'llama-3.1-8b'}` whitelist before calling `update_function_configuration`

### `get_model_metrics()` Aggregation Detail

```
Scan model_metrics table → group by task_type:
  All tasks:
    avg_latency_ms, total_cost_usd, avg_cost_usd, models_used

  accuracy_evaluation only:
    avg_overall_accuracy
    avg_field_accuracy per classification field

  response_evaluation only:
    avg_confidence_score
    avg_eval_scores per RAG dimension

Also group by model_name:
  count, total_cost_usd, avg_latency_ms
```

---

## 12. `sagemaker_inference`

**Trigger:** POST `/api/model/inference` via API Gateway.

### Flow

```
1. OPTIONS request → 200 with CORS headers (preflight, no body)

2. Parse request body (two accepted formats):
        { "instances": ["text1", "text2", ...] }   ← list of strings
        { "text": "single string" }                 ← normalized to ["single string"]
        Neither present → 400 error

3. sagemaker_runtime.invoke_endpoint(
        EndpointName = SAGEMAKER_ENDPOINT_NAME,
        ContentType  = 'application/json',
        Accept       = 'application/json',
        Body         = json.dumps({"instances": instances})
   )

4. HuggingFace DLC response unwrapping:
        HF container serialises output_fn result as [json_string, "application/json"]
        Detect this shape (list of 2, first element is str) →
          json.loads(result[0]) to get real predictions dict

5. Return { statusCode:200, predictions: [...] }

Error responses:
  400 → bad/missing request body or invalid JSON
  503 → ModelNotReadyException (endpoint still warming up)
  502 → ClientError from SageMaker (upstream inference failure)
  500 → unexpected exception
```

---

## Environment Variables Summary

| Lambda | Key env vars |
|---|---|
| `gmail_imap_poller` | `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `S3_BUCKET`, `STATE_MACHINE_ARN`, `IMAP_SERVER`, `MARK_AS_READ` |
| `email_parser` | `EMAIL_TABLE_NAME` |
| `classify_intent` | `EMAIL_TABLE_NAME`, `MODEL_METRICS_TABLE_NAME`, `ACTIVE_MODEL` |
| `extract_entity` | `ENTITY_MODEL_ID`, `AWS_REGION` |
| `rag_retrieval` | `EMBEDDINGS_TABLE_NAME` |
| `crm_validation` | `CUSTOMERS_TABLE_NAME`, `TEXT2SQL_MODEL_ID`, `AWS_REGION` |
| `claude_response` | `EMAIL_TABLE_NAME`, `MODEL_METRICS_TABLE_NAME`, `ACTIVE_MODEL` |
| `email_sender` | `EMAIL_TABLE_NAME`, `SENDER_EMAIL`, `SENDER_NAME` |
| `save_result` | `PIPELINE_RESULTS_TABLE_NAME` |
| `rag_ingestion` | `EMBEDDINGS_TABLE_NAME` |
| `api_handlers` | `EMAIL_TABLE_NAME`, `MODEL_METRICS_TABLE_NAME`, `EMBEDDINGS_TABLE_NAME`, `LOGS_BUCKET_NAME`, `EMAIL_SENDER_FUNCTION_NAME`, `CLASSIFY_INTENT_FUNCTION_NAME`, `CLAUDE_RESPONSE_FUNCTION_NAME` |
| `sagemaker_inference` | `SAGEMAKER_ENDPOINT_NAME` |

---

## Bedrock Models Used

| Model | ID | Used by |
|---|---|---|
| Claude 3 Haiku | `anthropic.claude-3-haiku-20240307-v1:0` | `extract_entity` (extraction), `rag_retrieval` (HyDE + rerank) |
| Claude 3 Sonnet | `anthropic.claude-3-sonnet-20240229-v1:0` | (referenced in config, available as override) |
| Mistral 7B | `mistral.mistral-7b-instruct-v0:2` | `classify_intent`, `claude_response`, `crm_validation` |
| Llama 3.1 8B | `meta.llama3-8b-instruct-v1:0` | `classify_intent`, `claude_response` (alternate/judge) |
| Titan Embeddings V2 | `amazon.titan-embed-text-v2:0` | `rag_retrieval`, `rag_ingestion` |
