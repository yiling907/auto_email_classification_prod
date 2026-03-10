# Laya Synthetic Dataset — Schema & Data Relationships

Synthetic Irish health insurance shared-mailbox dataset. All records are fictional.

**Dataset name:** `laya_like_synthetic_email_ops_starter`
**Created:** 2026-03-07

---

## Record Counts

| File | Records |
|------|--------:|
| `customers.jsonl` | 1,000 |
| `emails.jsonl` | 1,000 |
| `cases.jsonl` | 1,000 |
| `draft_responses.jsonl` | 1,000 |
| `attachments.jsonl` | 1,044 |
| `attachment_content.jsonl` | 1,044 |
| `knowledge_docs.jsonl` | 312 |

---

## Entity Relationship Diagram

```
customers (1,000)
    │
    │ customer_id
    ▼
emails (1,000) ──────────────────────────────────► customers
    │  email_id                                     (customer_id)
    │
    ├──► cases (1,000)            1:1   email_id → email_id
    │        │
    │        │ draft_response_id
    │        ▼
    │    draft_responses (1,000)  1:1   draft_response_id → draft_response_id
    │        │
    │        │ grounded_doc_ids[]
    │        ▼
    │    knowledge_docs (312)     M:N   (each draft references ~2 docs)
    │
    └──► attachments (1,044)      1:N   email_id → email_id
             │  attachment_id
             │  raw_text_ref
             ▼
         attachment_content (1,044)  1:1  attachment_id → attachment_id
                                          raw_text_ref → raw_text_id
```

### Join Keys (all 100% integrity verified)

| From | Field | To | Field |
|------|-------|----|-------|
| `emails` | `customer_id` | `customers` | `customer_id` |
| `cases` | `email_id` | `emails` | `email_id` |
| `cases` | `draft_response_id` | `draft_responses` | `draft_response_id` |
| `draft_responses` | `case_id` | `cases` | `case_id` |
| `draft_responses` | `grounded_doc_ids[]` | `knowledge_docs` | `doc_id` |
| `attachments` | `email_id` | `emails` | `email_id` |
| `attachments` | `linked_case_id` | `cases` | `case_id` |
| `attachments` | `raw_text_ref` | `attachment_content` | `raw_text_id` |
| `attachment_content` | `attachment_id` | `attachments` | `attachment_id` |

---

## File Schemas

### `customers.jsonl`

Customer / policyholder master record.

| Field | Type | Description | Values / Notes |
|-------|------|-------------|----------------|
| `customer_id` | string | Primary key | `CUST-000001` … `CUST-001000` |
| `member_id` | string | Member identifier | `MEM-000001` … |
| `full_name` | string | Full name | Irish names |
| `dob` | string | Date of birth | ISO 8601 (`YYYY-MM-DD`) |
| `email` | string | Email address | `@emaildemo.ie` domain |
| `phone` | string | Phone number | Irish `+353` format |
| `address` | string | Street address | Irish addresses |
| `county` | string | Irish county | `Clare` `Cork` `Dublin` `Galway` `Kildare` `Kilkenny` `Limerick` `Meath` `Waterford` `Wicklow` |
| `plan_name` | string | Insurance plan | `Corporate Flex` `Essential Care` `Everyday Care` `Family Plus` `HealthWise Gold` `Select Hospital` |
| `policy_number` | string | Policy reference | `POL-IE-XXXXXX` |
| `policy_start_date` | string | Policy start | ISO 8601 date |
| `renewal_date` | string | Annual renewal date | ISO 8601 date |
| `family_status` | string | Household type | `single` `couple` `family` |
| `member_count` | integer | Number of members on policy | 1–4 |
| `payment_method` | string | Payment method | `card` `direct_debit` `payroll_deduction` |
| `preferred_language` | string | Language | `en` |

---

### `emails.jsonl`

Inbound customer emails — the core entity for classification and routing.

| Field | Type | Description | Values / Notes |
|-------|------|-------------|----------------|
| `email_id` | string | Primary key | `EML-000001` … |
| `thread_id` | string | Conversation thread | `THR-000001` … |
| `message_index` | integer | Position in thread | `1` = first message |
| `received_at` | string | Receipt timestamp | ISO 8601 UTC |
| `channel` | string | Channel type | `email` |
| `mailbox` | string | Receiving mailbox | See below |
| `customer_id` | string | FK → `customers` | |
| `member_id` | string | Member reference | May be empty |
| `policy_number` | string | Policy mentioned in email | May be empty |
| `sender_name` | string | Sender display name | |
| `sender_email` | string | Sender email address | |
| `subject` | string | Email subject line | |
| `body_text` | string | Plain text body | |
| `body_html` | string | HTML body | |
| `detected_language` | string | Language detected | `en` |
| `customer_intent` | string | **Gold label — primary intent** | 17 classes (see below) |
| `secondary_intent` | string | Secondary intent if present | May be empty |
| `business_line` | string | Business domain | `health_insurance` |
| `urgency` | string | Urgency level | `low` `medium` `high` |
| `sentiment` | string | Customer sentiment | `positive` `neutral` `frustrated` `upset` |
| `has_attachment` | boolean | Email has attachment(s) | |
| `attachment_count` | integer | Number of attachments | 0–3 |
| `requires_human_review` | boolean | **Gold label — escalation flag** | Used for calibration evaluation |
| `gold_route_team` | string | **Gold label — routing target** | 12 teams (see below) |
| `gold_priority` | string | **Gold label — priority** | `normal` `high` `urgent` |
| `pii_present` | boolean | Contains PII | |
| `medical_terms_present` | boolean | Contains medical terminology | |
| `status_in_demo` | string | Demo status | `new` |

**Mailboxes (8):**
`authorisations@demohealth.ie` · `billing@demohealth.ie` · `brokers@demohealth.ie` · `claims@demohealth.ie` · `info@demohealth.ie` · `renewals@demohealth.ie` · `sales@demohealth.ie` · `support@demohealth.ie`

**`customer_intent` — 17 classes:**

| Intent | Description |
|--------|-------------|
| `broker_query` | Query from or about a broker |
| `cancellation_request` | Request to cancel policy |
| `claim_reimbursement_query` | Query about reimbursement of a paid claim |
| `claim_status` | Check status of an existing claim |
| `claim_submission` | Submitting a new claim |
| `complaint` | Formal or informal complaint |
| `coverage_query` | What is / isn't covered |
| `dependent_addition` | Adding a family member to policy |
| `document_followup` | Chasing a previously submitted document |
| `enrollment_new_policy` | Applying for a new policy |
| `hospital_network_query` | Which hospitals / providers are in network |
| `id_verification` | Identity verification request |
| `other` | Does not fit any category |
| `payment_issue` | Payment failure, DD problem, billing dispute |
| `policy_change` | Change plan, address, or policy details |
| `pre_authorisation` | Pre-auth request for upcoming treatment |
| `renewal_query` | Query about policy renewal |

**`gold_route_team` — 12 teams:**

| Team | Typical intents |
|------|----------------|
| `claims_team` | `claim_submission` `claim_status` `claim_reimbursement_query` |
| `complaints_team` | `complaint` |
| `customer_support_team` | `coverage_query` |
| `finance_support_team` | `payment_issue` |
| `general_support_team` | `broker_query` `other` |
| `medical_review_team` | `pre_authorisation` |
| `operations_team` | `document_followup` `id_verification` |
| `policy_admin_team` | `policy_change` `dependent_addition` |
| `provider_support_team` | `hospital_network_query` |
| `renewals_team` | `renewal_query` |
| `retention_team` | `cancellation_request` |
| `sales_enrollment_team` | `enrollment_new_policy` |

---

### `cases.jsonl`

Back-office case created for each email. 1:1 with `emails`.

| Field | Type | Description | Values / Notes |
|-------|------|-------------|----------------|
| `case_id` | string | Primary key | `CASE-000001` … |
| `email_id` | string | FK → `emails` | |
| `thread_id` | string | Conversation thread | |
| `customer_id` | string | FK → `customers` | |
| `member_id` | string | Member reference | |
| `policy_number` | string | Policy reference | |
| `case_type` | string | Case category (mirrors `customer_intent`) | 17 values |
| `sub_type` | string | Secondary category | May be empty |
| `route_team` | string | Assigned team | 12 teams (same as `gold_route_team`) |
| `route_queue` | string | Specific queue within team | 15 values (see below) |
| `case_priority` | string | Priority level | `normal` `high` `urgent` |
| `sla_hours` | integer | SLA in hours | `12` `24` `48` `72` |
| `extracted_entities_json` | object | Extracted fields from email / attachment | Schema varies by `case_type` (see below) |
| `attachments_present` | boolean | Case has attachments | |
| `missing_documents_json` | array | List of outstanding docs | `[]` or `["supporting_document"]` |
| `rag_context_group` | string | RAG retrieval group | `billing` `claims` `complaints` `coverage` `network` `policy_servicing` `preauth` `renewals` |
| `draft_response_id` | string | FK → `draft_responses` | |
| `human_review_required` | boolean | Requires human review | |
| `resolution_status` | string | Current resolution state | `pending` `open` `resolved` |
| `final_outcome` | string | Final decision | `approved` `rejected` `info_requested` `pending_review` |
| `created_at` | string | Case creation timestamp | ISO 8601 UTC |
| `updated_at` | string | Last update timestamp | ISO 8601 UTC |

**`route_queue` — 15 values:**
`billing_queue` · `cancellations` · `claims_followup` · `claims_new` · `claims_payment_review` · `complaints_queue` · `coverage_help` · `document_processing` · `enrollment_new` · `manual_triage` · `member_changes` · `preauth_queue` · `provider_network` · `renewal_support` · `servicing_queue`

**`extracted_entities_json` — schema by `case_type`:**

| case_type | Fields |
|-----------|--------|
| `claim_submission` `claim_status` `hospital_network_query` `cancellation_request` `other` | `provider_name` `provider_type` `invoice_number` `invoice_date` `treatment_date` `patient_name` `member_id` `treatment_type` `diagnosis_text` `amount` `currency` `tax_amount` `receipt_present` |
| `coverage_query` | `form_id` `patient_name` `consultant_name` `hospital_name` `proposed_treatment` `treatment_date` `estimated_cost` `diagnosis_text` `urgency_level` `referrer_name` `referral_reason` `referral_date` |
| `pre_authorisation` | `patient_name` `hospital_name` `discharge_date` |
| `claim_reimbursement_query` `renewal_query` | `renewal_year` `old_premium` `new_premium` `renewal_date` `plan_name` `member_count` |
| `payment_issue` | `bank_name` `iban_masked` `account_holder` |
| `complaint` | `complaint_topic` `member_name` |
| `dependent_addition` `id_verification` `policy_change` | `document_type` `full_name` `date_of_birth` `document_number` `expiry_date` `address_present` |
| `document_followup` | `claim_reference` `policy_number` `member_name` `treatment_type` `amount_claimed` |
| `broker_query` `enrollment_new_policy` | `plan_name` `member_name` `policy_number` |

---

### `draft_responses.jsonl`

AI-generated draft reply for each case. 1:1 with `cases`.

| Field | Type | Description | Values / Notes |
|-------|------|-------------|----------------|
| `draft_response_id` | string | Primary key | `DRF-000001` … |
| `case_id` | string | FK → `cases` | |
| `response_type` | string | Type of response | `acknowledgement` `explanation` `info_request` |
| `tone` | string | Tone of reply | `neutral` `empathetic` |
| `grounded_doc_ids` | array | FK[] → `knowledge_docs.doc_id` | Always 2 doc IDs |
| `generated_summary` | string | One-line case summary | |
| `generated_reply` | string | **Full draft email reply** (reference response for RAG eval) | |
| `missing_info_list` | array | Fields still needed from customer | Usually `[]` |
| `escalation_flag` | boolean | Should be escalated to human | |
| `compliance_notes` | string | Compliance guidance for agent | |

---

### `attachments.jsonl`

Attachment metadata. 1:N with `emails` (1,044 attachments across 633 emails).

| Field | Type | Description | Values / Notes |
|-------|------|-------------|----------------|
| `attachment_id` | string | Primary key | `ATT-000001` … |
| `email_id` | string | FK → `emails` | |
| `file_name` | string | Original file name | |
| `file_type` | string | File extension | `pdf` `jpg` `png` |
| `mime_type` | string | MIME type | `application/pdf` `image/jpg` `image/png` |
| `doc_category` | string | Document category | 14 values (see below) |
| `page_count` | integer | Number of pages | 1–4 |
| `language` | string | Document language | `en` |
| `ocr_required` | boolean | Needs OCR processing | |
| `extraction_difficulty` | string | Extraction difficulty | `easy` `medium` `hard` |
| `contains_handwriting` | boolean | Has handwritten content | |
| `contains_tables` | boolean | Has table data | |
| `contains_logo` | boolean | Has company logo | |
| `contains_signature` | boolean | Has signature | |
| `linked_case_id` | string | FK → `cases` | |
| `gold_extraction_template` | string | Template used for extraction | 10 values (see below) |
| `raw_text_ref` | string | FK → `attachment_content.raw_text_id` | |

**`doc_category` — 14 values:**
`bank_proof` · `claim_form` · `complaint_letter` · `consultant_receipt` · `dental_invoice` · `discharge_summary` · `gp_referral_letter` · `id_document` · `medical_invoice` · `membership_certificate` · `optical_receipt` · `physiotherapy_invoice` · `preauth_form` · `renewal_notice`

**`gold_extraction_template` — 10 values:**
`bank_v1` · `claim_form_v1` · `clinical_letter_v1` · `complaint_v1` · `discharge_v1` · `id_v1` · `invoice_v1` · `membership_v1` · `preauth_v1` · `renewal_v1`

---

### `attachment_content.jsonl`

OCR / extracted text and gold field values for each attachment. 1:1 with `attachments`.

| Field | Type | Description | Values / Notes |
|-------|------|-------------|----------------|
| `raw_text_id` | string | Primary key | `OCR-000001` … |
| `attachment_id` | string | FK → `attachments` | |
| `doc_category` | string | Document category | Mirrors `attachments.doc_category` |
| `raw_text` | string | Full extracted / OCR text | |
| `structured_gold_fields` | object | **Gold-standard extracted fields** (used for entity extraction evaluation) | Schema varies by `doc_category` (see below) |

**`structured_gold_fields` — schema by `doc_category`:**

| doc_category | Fields |
|---|---|
| `bank_proof` | `bank_name` · `iban_masked` · `account_holder` |
| `claim_form` | `claim_reference` · `policy_number` · `member_name` · `treatment_type` · `amount_claimed` |
| `complaint_letter` | `complaint_topic` · `member_name` |
| `consultant_receipt` `dental_invoice` `medical_invoice` `optical_receipt` `physiotherapy_invoice` | `provider_name` · `provider_type` · `invoice_number` · `invoice_date` · `treatment_date` · `patient_name` · `member_id` · `treatment_type` · `diagnosis_text` · `amount` · `currency` · `tax_amount` · `receipt_present` |
| `discharge_summary` | `patient_name` · `hospital_name` · `discharge_date` |
| `gp_referral_letter` | `referrer_name` · `patient_name` · `referral_reason` · `referral_date` |
| `id_document` | `document_type` · `full_name` · `date_of_birth` · `document_number` · `expiry_date` · `address_present` |
| `membership_certificate` | `plan_name` · `member_name` · `policy_number` |
| `preauth_form` | `form_id` · `patient_name` · `consultant_name` · `hospital_name` · `proposed_treatment` · `treatment_date` · `estimated_cost` · `diagnosis_text` · `urgency_level` |
| `renewal_notice` | `renewal_year` · `old_premium` · `new_premium` · `renewal_date` · `plan_name` · `member_count` |

---

### `knowledge_docs.jsonl`

Knowledge base chunks used for RAG retrieval. Referenced by `draft_responses.grounded_doc_ids`.

| Field | Type | Description | Values / Notes |
|-------|------|-------------|----------------|
| `doc_id` | string | Primary key | `DOC-000001` … `DOC-000312` |
| `title` | string | Document title | |
| `doc_type` | string | Document type | `faq` `policy` `sop` `template` |
| `business_area` | string | Business domain | `billing` `claims` `complaints` `coverage` `network` `policy_servicing` `preauth` `renewals` |
| `audience` | string | Intended audience | `agent` `both` |
| `version` | string | Document version | e.g. `v1.5` |
| `effective_date` | string | Date document became effective | ISO 8601 date |
| `jurisdiction` | string | Legal jurisdiction | `IE` |
| `product_type` | string | Product line | `health_insurance` |
| `tags` | array | Keyword tags | String array |
| `chunk_id` | string | Chunk identifier | `DOC-XXXXXX-CH-XX` |
| `chunk_text` | string | **RAG chunk text** — content used for retrieval | |
| `parent_doc_ref` | string | Parent document reference | e.g. `CLAIMS-001` |
| `approved_for_rag` | boolean | Approved for RAG use | Always `true` in this dataset |
| `escalation_required` | boolean | Chunk topic requires escalation | |

---

## Key Design Notes

1. **Every email has exactly one case and one draft response** — the three files join 1:1 via `email_id` / `case_id` / `draft_response_id`.

2. **Attachments are optional and multi-valued** — 633 of 1,000 emails have at least one attachment; the remaining 367 have none. Average ~1.65 attachments per email that has them.

3. **`customer_intent` is the primary classification target** — 17 classes, directly mirrored in `cases.case_type` and used to drive `gold_route_team` routing.

4. **`requires_human_review` / `human_review_required`** — the calibration label for confidence-threshold evaluation. Appears in both `emails` and `cases`.

5. **`structured_gold_fields` in `attachment_content`** — gold-standard ground truth for entity extraction evaluation, schema varies by `doc_category`.

6. **`grounded_doc_ids` in `draft_responses`** — always references exactly 2 `knowledge_docs` records; used to evaluate RAG faithfulness (does the response stay grounded?).

7. **`rag_context_group` in `cases`** — groups cases into 8 retrieval domains (`billing`, `claims`, `complaints`, `coverage`, `network`, `policy_servicing`, `preauth`, `renewals`), aligned with `knowledge_docs.business_area`.
