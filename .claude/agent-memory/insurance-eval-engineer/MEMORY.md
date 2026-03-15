# InsureMail AI — Eval Engineer Agent Memory

## Key Architecture Facts
- classify_intent and claude_response Lambdas use Mistral-7B/Llama-3.1-8B as active models, NOT Claude 3 Sonnet (ARCH-01, ARCH-02). This is a known gap vs CLAUDE.md spec.
- Confidence blending: 50% LLM judge + 50% RAG similarity. Zero RAG docs → confidence always < 0.5 → always escalates (ARCH-03).
- rag_retrieval uses Haiku (cross-encoder reranker + HyDE). Titan Embed V2 (1024-dim). Full DynamoDB scan on every call (PERF-01).
- email_parser `_detect_pii()` checks email/phone/PPSN only — does NOT flag policy numbers (POL-IE-XXXXXX) or member IDs (MEM-XXXXXX).

## Gold Label Conventions (Laya Dataset)
- `pii_present=True` is set for any email containing a policy number or member ID (broader than email_parser's regex). See ENTITY-02.
- `requires_human_review`: True ~27% of laya emails; True for ALL complaint + pre_authorisation intents.
- 17 intents; 12 route teams. Intent→route is deterministic via INTENT_TO_ROUTE map in classify_intent Lambda.
- Laya dataset: 1000 emails, 1000 cases, 1000 drafts. Cases join 1:1 via email_id/case_id/draft_response_id.
- `rag_context_group` in cases.jsonl is ground truth for RAG domain alignment (8 groups: claims, coverage, billing, etc.)

## E2E Assessment Script (scripts/run_e2e_assessment.py)
- Fully local dry-run (no AWS). Uses gold intent labels as predicted (perfect classifier sim) in dry-run mode.
- 6 metric stages: intent classification, routing, entity extraction, RAG hit rate, response quality, confidence calibration.
- Confidence heuristic: base score per intent + urgency/sentiment/attachment adjustments.
- PII detection extended to include POL-IE- and MEM- patterns (unlike Lambda, to match gold labels).
- Output: results/e2e_assessment_YYYYMMDD.json + stdout summary.

## Entity Extraction Edge Cases
- Claim references in test emails use format `CLM-YYYYMMDD` (8+ digit suffix), not the older `CLM-XXXXXXXX` pattern. Low extraction rate is expected as most test emails don't mention claim refs in body.
- Member ID regex (`MEM-\d{6}`) only matches when explicitly written in body; many emails only have it in metadata fields.
- Amount extraction rate is low (~10-24%) because EUR amounts only appear in claim/payment emails.

## Test Dataset (tests/test_data/e2e_test_emails.jsonl)
- 50 emails, all 17 intents, all 12 route teams. Linked schemas match laya convention.
- expected_confidence_band: high=41, medium=9 (no low-confidence emails — intent is always clear in test set).
- Fields include: email_id (E2E-XXXXXX), expected_confidence_band (not in laya schema).

## Recurring Patterns Across Evaluation Runs
- Routing accuracy = 1.0 whenever intent is gold (INTENT_TO_ROUTE is deterministic). Real-world routing accuracy is bounded by intent accuracy.
- ECE is elevated (~0.17-0.21) because upset/frustrated emails get confidence penalty that doesn't match binary accuracy. Calibration improves when sentiment is ignored in confidence calc.
- RAG hit rate ~0.92-0.98 in dry-run; the 2-8% miss is `other` intent (no RAG group) + a few multi-intent ambiguous cases.

## Detailed Findings Reference
See scripts/run_e2e_assessment.py `_assess_code_quality()` for 8 findings:
ARCH-01 (HIGH), ARCH-02 (HIGH), ARCH-03 (MEDIUM), ENTITY-01 (LOW), ENTITY-02 (MEDIUM), EVAL-01 (MEDIUM), LOGIC-01 (LOW), PERF-01 (MEDIUM)
