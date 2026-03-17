#!/usr/bin/env python3
"""
InsureMail AI — Step Function End-to-End Demo
==============================================
Builds realistic test emails (with MIME attachments), uploads them to S3,
triggers the AWS Step Functions pipeline, waits for completion, and prints
the full structured output from every stage.

Pipeline stages exercised
─────────────────────────
  ParseEmail        — email_parser Lambda
                        • RFC 2822 body + attachment extraction (PDF/DOCX/TXT)
                        • 14-category doc_category classification
                        • structured_gold_fields extraction
  ParallelAnalysis  — classify_intent Lambda (intent / urgency / sentiment / route)
                      + entity extraction (policy_number, member_id, …)
  RetrieveKnowledge — rag_retrieval Lambda (Titan V2 embeddings + RRF fusion)
  ValidateCRM       — crm_validation Lambda (Text-to-SQL → DynamoDB customer lookup)
  GenerateResponse  — claude_response Lambda (Claude 3 Sonnet + confidence score)
  Route             — DetermineAction (auto_response / human_review / escalate)

Two demo test cases
───────────────────
  Case 1 – COVERAGE QUERY
    Orla Quinn | POL-IE-118369 | Family Plus
    Asks about knee-surgery pre-authorisation limits.
    Attachment: pre-auth form (TXT → doc_category = preauth_form)

  Case 2 – CLAIM SUBMISSION
    Ciara Kelly | POL-IE-929538 | HealthWise Gold
    Submits a physiotherapy claim with invoice.
    Attachment: physiotherapy invoice (TXT → doc_category = physiotherapy_invoice)

Usage
─────
    python scripts/StepFunctionAssignment.py               # run both cases
    python scripts/StepFunctionAssignment.py --case 1      # run case 1 only
    python scripts/StepFunctionAssignment.py --case 2      # run case 2 only
    python scripts/StepFunctionAssignment.py --dry-run     # build payload, skip AWS

Environment variables (optional overrides)
──────────────────────────────────────────
    AWS_REGION          (default: us-east-1)
    EMAIL_BUCKET        (default: insuremail-ai-dev-emails)
    STATE_MACHINE_ARN   (default: arn:aws:states:us-east-1:…)
    EXEC_TIMEOUT_SEC    (default: 180)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
import uuid
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import boto3

# ── AWS config ────────────────────────────────────────────────────────────────

REGION            = os.environ.get("AWS_REGION",       "us-east-1")
EMAIL_BUCKET      = os.environ.get("EMAIL_BUCKET",     "insuremail-ai-dev-emails")
STATE_MACHINE_ARN = os.environ.get(
    "STATE_MACHINE_ARN",
    "arn:aws:states:us-east-1:970850578809:stateMachine:"
    "insuremail-ai-dev-email-processing",
)
EXEC_TIMEOUT_SEC  = int(os.environ.get("EXEC_TIMEOUT_SEC", "180"))
S3_PREFIX         = "assignment-demo"
POLL_INTERVAL_SEC = 3

# ── AWS clients ───────────────────────────────────────────────────────────────

sfn = boto3.client("stepfunctions", region_name=REGION)
s3  = boto3.client("s3",            region_name=REGION)

# ══════════════════════════════════════════════════════════════════════════════
# Test cases
# ══════════════════════════════════════════════════════════════════════════════
# Each case contains:
#   • metadata used to build the MIME email
#   • an attachment (TXT text that the email_parser Lambda will classify
#     and extract structured fields from)
#   • expected_output for quick pass/fail validation after execution
# ══════════════════════════════════════════════════════════════════════════════

TEST_CASES: List[Dict[str, Any]] = [

    # ── Case 1: Coverage Query ────────────────────────────────────────────────
    {
        "case_id":      "case-01-coverage-query",
        "description":  "Pre-auth / coverage query for knee surgery",
        "sender_name":  "Orla Quinn",
        "sender_email": "orla.quinn82@emaildemo.ie",
        "to_email":     "support@insuremail.ie",
        "subject":      "Pre-authorisation query for knee surgery — policy POL-IE-118369",
        "body_text": textwrap.dedent("""\
            Hi,

            I am writing to ask about pre-authorisation for an orthopaedic procedure.

            My policy number is POL-IE-118369 and my member ID is MEM-000860.

            My GP has referred me to a consultant at Blackrock Clinic, Dublin, for
            a right knee arthroscopy.  The estimated cost from the consultant is €4,200.

            Could you please confirm:
            1. Whether my Family Plus plan covers this procedure at Blackrock Clinic?
            2. The maximum annual limit for orthopaedic procedures?
            3. Whether I need written pre-authorisation before the procedure date?

            I have attached the pre-authorisation request form completed by my GP
            (Dr. Eoin Murphy, Meath Primary Care).

            Kind regards,
            Orla Quinn
            DOB: 15/09/1981
            Phone: +353872873734
        """),

        # Attachment: GP-filled pre-auth form — classified as preauth_form by email_parser
        "attachment_filename": "preauth_request.txt",
        "attachment_content": textwrap.dedent("""\
            LAYA HEALTHCARE — PRE-AUTHORISATION REQUEST FORM
            Form ID: PA-2026-03-118369

            PATIENT DETAILS
            Patient Name   : Orla Quinn
            Member ID      : MEM-000860
            Policy Number  : POL-IE-118369
            Date of Birth  : 15/09/1981

            TREATING CONSULTANT
            Consultant Name: Mr. Cormac Fitzpatrick
            Specialty      : Orthopaedic Surgery
            Hospital       : Blackrock Clinic, Rock Road, Blackrock, Co. Dublin

            PROPOSED TREATMENT
            Procedure      : Right Knee Arthroscopy (CPT 29881)
            Diagnosis      : Medial meniscus tear (ICD-10: M23.202)
            Proposed Date  : 15/04/2026
            Estimated Cost : EUR 4,200.00

            CLINICAL URGENCY
            Urgency Level  : Elective

            REFERRING GP
            Referrer Name  : Dr. Eoin Murphy
            Practice       : Meath Primary Care Centre
            Referral Date  : 10/03/2026

            GP Signature   : E. Murphy MD
            Date           : 10/03/2026
        """),

        # Expected pipeline outputs (used for result validation)
        "expected_intent":     "pre_authorisation",
        "expected_crm_found":  True,
        "expected_policy_num": "POL-IE-118369",
        "expected_doc_category": "preauth_form",
    },

    # ── Case 2: Claim Submission ───────────────────────────────────────────────
    {
        "case_id":      "case-02-claim-submission",
        "description":  "Physiotherapy claim submission with invoice",
        "sender_name":  "Ciara Kelly",
        "sender_email": "ciara.kelly40@inboxsample.ie",
        "to_email":     "claims@insuremail.ie",
        "subject":      "Claim submission — physiotherapy invoice — POL-IE-929538",
        "body_text": textwrap.dedent("""\
            Dear Claims Team,

            I would like to submit a claim for physiotherapy treatment received in
            February 2026.

            My details:
              Policy Number : POL-IE-929538
              Member ID     : MEM-000114
              Plan          : HealthWise Gold

            I attended six physiotherapy sessions at Kildare Physio & Sports Clinic
            between 02/02/2026 and 20/02/2026 following a sports injury to my lower back.

            The invoice is attached.  Total amount claimed: €420.00 (6 × €70).

            Please confirm receipt and let me know the expected processing time.

            Many thanks,
            Ciara Kelly
        """),

        # Attachment: physiotherapy invoice — classified as physiotherapy_invoice by email_parser
        "attachment_filename": "physio_invoice_feb2026.txt",
        "attachment_content": textwrap.dedent("""\
            KILDARE PHYSIO & SPORTS CLINIC
            Unit 3, Naas Business Park, Naas, Co. Kildare
            Tel: +353 45 987654  |  VAT: IE9876543B

            INVOICE
            Invoice Number : KP-2026-0214
            Invoice Date   : 28/02/2026
            Treatment Date : 02/02/2026 – 20/02/2026

            PATIENT DETAILS
            Patient Name   : Ciara Kelly
            Member ID      : MEM-000114
            Date of Birth  : 25/04/1983

            PROVIDER DETAILS
            Provider Name  : Kildare Physio & Sports Clinic
            Provider Type  : Physiotherapy

            TREATMENT DETAILS
            Treatment Type : Manual Physiotherapy — Lumbar Spine Rehabilitation
            Diagnosis      : Lumbar strain / lower back pain (ICD-10: M54.5)
            Sessions       : 6

            CHARGES
            Unit Price     : EUR 70.00
            Sessions       : 6
            Sub-Total      : EUR 420.00
            VAT (0%)       : EUR 0.00
            Total Amount   : EUR 420.00

            PAYMENT
            Receipt Present: Yes
            Payment Method : Card
        """),

        "expected_intent":     "claim_submission",
        "expected_crm_found":  True,
        "expected_policy_num": "POL-IE-929538",
        "expected_doc_category": "physiotherapy_invoice",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# Step 1 — Build MIME email
# ══════════════════════════════════════════════════════════════════════════════

def build_mime_email(case: Dict[str, Any]) -> str:
    """
    Construct a multipart RFC 2822 email with a plain-text body and a
    TXT attachment.  The attachment text is written in a format that
    the email_parser Lambda's document classifier will recognise and
    extract structured fields from (matching attachment_content.jsonl schema).
    """
    msg = MIMEMultipart("mixed")
    msg["From"]       = f"{case['sender_name']} <{case['sender_email']}>"
    msg["To"]         = case["to_email"]
    msg["Subject"]    = case["subject"]
    msg["Date"]       = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg["Message-ID"] = f"<{case['case_id']}@assignment.insuremail.ie>"

    # Plain-text body
    msg.attach(MIMEText(case["body_text"], "plain", "utf-8"))

    # TXT attachment (classified + parsed by email_parser Lambda)
    attachment_bytes = case["attachment_content"].encode("utf-8")
    part = MIMEBase("text", "plain")
    part.set_payload(attachment_bytes)
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        "attachment",
        filename=case["attachment_filename"],
    )
    msg.attach(part)

    return msg.as_string()


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 — Upload to S3
# ══════════════════════════════════════════════════════════════════════════════

def upload_email_to_s3(run_id: str, case: Dict[str, Any], eml: str) -> str:
    """Upload raw MIME email to S3; return the S3 object key."""
    key = f"{S3_PREFIX}/{run_id}/{case['case_id']}.eml"
    s3.put_object(
        Bucket=EMAIL_BUCKET,
        Key=key,
        Body=eml.encode("utf-8"),
        ContentType="message/rfc822",
    )
    print(f"    Uploaded → s3://{EMAIL_BUCKET}/{key}")
    return key


# ══════════════════════════════════════════════════════════════════════════════
# Step 3 — Start Step Functions execution
# ══════════════════════════════════════════════════════════════════════════════

def start_execution(run_id: str, case_id: str, s3_key: str) -> str:
    """
    Start a Step Functions execution.

    Input payload: { "bucket": "...", "key": "..." }
    This is what the ParseEmail state expects — it fetches the raw email
    from S3, parses it (including attachments), then passes the result
    downstream to ParallelAnalysis, RAG, CRM, and GenerateResponse.
    """
    # SFN execution names: max 80 chars, [a-zA-Z0-9_-] only
    exec_name = f"demo-{case_id[:20]}-{run_id[:8]}".replace("_", "-")

    payload = {
        "bucket": EMAIL_BUCKET,
        "key":    s3_key,
    }

    resp = sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=exec_name,
        input=json.dumps(payload),
    )
    exec_arn = resp["executionArn"]
    print(f"    Execution started → {exec_arn.split(':')[-1]}")
    return exec_arn


# ══════════════════════════════════════════════════════════════════════════════
# Step 4 — Poll until terminal state
# ══════════════════════════════════════════════════════════════════════════════

def poll_execution(exec_arn: str, timeout: int = EXEC_TIMEOUT_SEC) -> Dict[str, Any]:
    """
    Poll the Step Function execution until it reaches a terminal state
    (SUCCEEDED, FAILED, TIMED_OUT, ABORTED) or until our client-side
    timeout is reached.

    Returns { status, output (parsed JSON), error, duration_sec }
    """
    t0       = time.monotonic()
    deadline = t0 + timeout
    dots     = 0

    while time.monotonic() < deadline:
        resp   = sfn.describe_execution(executionArn=exec_arn)
        status = resp["status"]

        if status == "SUCCEEDED":
            duration = time.monotonic() - t0
            output   = json.loads(resp.get("output", "{}"))
            print(f"\r    Done ✓  ({duration:.1f}s)                        ")
            return {"status": "SUCCEEDED", "output": output, "error": None,
                    "duration_sec": round(duration, 1)}

        if status in ("FAILED", "TIMED_OUT", "ABORTED"):
            duration = time.monotonic() - t0
            print(f"\r    {status}  ({duration:.1f}s)                       ")
            return {
                "status":       status,
                "output":       {},
                "error":        f"{resp.get('error', status)}: {resp.get('cause', '')[:300]}",
                "duration_sec": round(duration, 1),
            }

        # Still running — show a progress indicator
        dots = (dots + 1) % 4
        elapsed = time.monotonic() - t0
        print(f"\r    Waiting{'.' * dots:<4} ({elapsed:.0f}s / {timeout}s)", end="", flush=True)
        time.sleep(POLL_INTERVAL_SEC)

    # Client-side timeout — stop the execution gracefully
    try:
        sfn.stop_execution(executionArn=exec_arn, cause="demo-client-timeout")
    except Exception:
        pass

    duration = time.monotonic() - t0
    print(f"\r    CLIENT TIMEOUT ({duration:.1f}s)                   ")
    return {
        "status":       "CLIENT_TIMEOUT",
        "output":       {},
        "error":        f"Exceeded client timeout of {timeout}s",
        "duration_sec": round(duration, 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Step 5 — Extract & display results
# ══════════════════════════════════════════════════════════════════════════════

def extract_results(output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pull the key outputs from each pipeline stage out of the Step Functions
    execution output and return them as a clean, flat result dict.
    """
    # ── Parsed email (email_parser Lambda) ────────────────────────────────────
    parsed_email = output.get("parsed_email", {})
    parsed_data  = parsed_email.get("parsed_data", {})
    attachments  = parsed_data.get("attachments_content", [])

    # ── Intent + routing (classify_intent Lambda) ─────────────────────────────
    analysis     = output.get("analysis", [{}])
    intent_block = analysis[0].get("intent", {}) if analysis else {}
    clf          = intent_block.get("classification", intent_block)

    # ── RAG (rag_retrieval Lambda) ─────────────────────────────────────────────
    rag_results  = output.get("rag_results", {})
    rag_docs     = rag_results.get("retrieved_documents", [])

    # ── CRM validation (crm_validation Lambda) ────────────────────────────────
    crm_context  = output.get("crm_context", {})

    # ── Response (claude_response Lambda) ─────────────────────────────────────
    response     = output.get("response", {})

    # ── Final routing decision ────────────────────────────────────────────────
    final_action = output.get("final_action", output.get("email_result", {}))

    return {
        # ── Email parsing
        "email_id":          parsed_email.get("email_id", ""),
        "sender_email":      parsed_data.get("sender_email", ""),
        "subject":           parsed_data.get("subject", ""),
        "body_preview":      (parsed_data.get("body_text", "")[:200] + "…"),
        "policy_number":     parsed_data.get("policy_number", ""),
        "member_id":         parsed_data.get("member_id", ""),
        "pii_present":       parsed_data.get("pii_present", False),
        "attachment_count":  parsed_data.get("attachment_count", 0),
        "attachments_content": attachments,

        # ── Intent classification
        "predicted_intent":  clf.get("customer_intent", clf.get("intent", "")),
        "urgency":           clf.get("urgency", ""),
        "sentiment":         clf.get("sentiment", ""),
        "route_team":        clf.get("gold_route_team", clf.get("route_team", "")),

        # ── RAG retrieval
        "rag_doc_count":     len(rag_docs),
        "rag_top_doc":       rag_docs[0].get("content", "")[:200] if rag_docs else None,

        # ── CRM validation
        "crm_found":          crm_context.get("crm_found", False),
        "crm_customer_name":  (crm_context.get("customer") or {}).get("full_name", ""),
        "crm_policy_status":  (crm_context.get("policy")   or {}).get("policy_status", ""),
        "crm_plan_name":      (crm_context.get("policy")   or {}).get("plan_name", ""),
        "crm_annual_limit":   (crm_context.get("policy")   or {}).get("annual_limit_eur"),
        "crm_eligible":       (crm_context.get("validation") or {}).get("eligible_for_intent"),
        "crm_ineligibility":  (crm_context.get("validation") or {}).get("ineligibility_reason"),
        "crm_lookup_field":   (crm_context.get("query_audit") or {}).get("lookup_field", ""),

        # ── Response generation
        "confidence_score":   response.get("confidence_score", 0.0),
        "action":             response.get("action", ""),
        "response_text":      response.get("response_text", ""),

        # ── Final action
        "final_action":       final_action.get("action", ""),
    }


def validate_results(case: Dict[str, Any], results: Dict[str, Any]) -> List[str]:
    """
    Compare extracted results against the expected values in the test case.
    Returns a list of failure messages (empty list = all pass).
    """
    failures = []

    def _check(label: str, expected: Any, actual: Any):
        if expected is None:
            return
        if str(actual).lower() != str(expected).lower():
            failures.append(f"  FAIL  {label}: expected={expected!r}  actual={actual!r}")

    _check("intent",     case.get("expected_intent"),     results["predicted_intent"])
    _check("crm_found",  case.get("expected_crm_found"),  results["crm_found"])

    # policy number extracted from parsed email
    expected_pol = case.get("expected_policy_num", "")
    if expected_pol and expected_pol not in results["policy_number"]:
        failures.append(
            f"  FAIL  policy_number: expected {expected_pol!r} "
            f"in parsed output, got {results['policy_number']!r}"
        )

    # doc_category of first attachment
    expected_cat = case.get("expected_doc_category", "")
    attachments  = results.get("attachments_content", [])
    if expected_cat and attachments:
        actual_cat = attachments[0].get("doc_category", "")
        if actual_cat != expected_cat:
            failures.append(
                f"  FAIL  doc_category: expected={expected_cat!r}  actual={actual_cat!r}"
            )

    return failures


def print_case_result(
    case:     Dict[str, Any],
    results:  Dict[str, Any],
    exec_arn: str,
    duration: float,
    status:   str,
    error:    Optional[str],
):
    """Pretty-print the full end-to-end result for one test case."""
    bar  = "═" * 76
    dash = "─" * 76

    print(f"\n{bar}")
    print(f"  TEST CASE  :  {case['case_id']}")
    print(f"  Description:  {case['description']}")
    print(f"  Status     :  {status}  ({duration:.1f}s)")
    print(f"  Exec ARN   :  …{exec_arn.split(':')[-1]}")
    print(bar)

    if status != "SUCCEEDED":
        print(f"\n  ERROR: {error or 'unknown'}")
        return

    # ── Stage 1: Email Parsing ────────────────────────────────────────────────
    print(f"\n  {dash}")
    print(f"  STAGE 1 — EMAIL PARSING")
    print(f"  {dash}")
    print(f"  Email ID        : {results['email_id']}")
    print(f"  Sender          : {results['sender_email']}")
    print(f"  Subject         : {results['subject']}")
    print(f"  Policy extracted: {results['policy_number'] or '(none)'}")
    print(f"  Member extracted: {results['member_id'] or '(none)'}")
    print(f"  PII present     : {results['pii_present']}")
    print(f"  Attachments     : {results['attachment_count']}")

    attachments = results.get("attachments_content", [])
    if attachments:
        print(f"\n  Parsed attachments  ({len(attachments)} total):")
        for i, att in enumerate(attachments, 1):
            print(f"\n    Attachment {i}:")
            print(f"      attachment_id  : {att.get('attachment_id', '')}")
            print(f"      raw_text_id    : {att.get('raw_text_id', '')}")
            print(f"      doc_category   : {att.get('doc_category', '')}")
            raw_preview = (att.get("raw_text") or "")[:120].replace("\n", " ")
            print(f"      raw_text       : {raw_preview}…")
            gold = att.get("structured_gold_fields", {})
            if gold:
                print(f"      structured_gold_fields:")
                for k, v in gold.items():
                    print(f"        {k:<25}: {v}")

    # ── Stage 2: Intent Classification ───────────────────────────────────────
    print(f"\n  {dash}")
    print(f"  STAGE 2 — INTENT CLASSIFICATION")
    print(f"  {dash}")
    print(f"  Intent          : {results['predicted_intent']}")
    print(f"  Urgency         : {results['urgency']}")
    print(f"  Sentiment       : {results['sentiment']}")
    print(f"  Route team      : {results['route_team']}")

    # ── Stage 3: RAG Retrieval ────────────────────────────────────────────────
    print(f"\n  {dash}")
    print(f"  STAGE 3 — RAG KNOWLEDGE RETRIEVAL")
    print(f"  {dash}")
    print(f"  Documents retrieved: {results['rag_doc_count']}")
    if results["rag_top_doc"]:
        print(f"  Top document preview:")
        for line in textwrap.wrap(results["rag_top_doc"], width=70):
            print(f"    {line}")

    # ── Stage 4: CRM Validation ───────────────────────────────────────────────
    print(f"\n  {dash}")
    print(f"  STAGE 4 — CRM VALIDATION")
    print(f"  {dash}")
    print(f"  CRM record found   : {results['crm_found']}")
    if results["crm_found"]:
        print(f"  Customer name      : {results['crm_customer_name']}")
        print(f"  Plan               : {results['crm_plan_name']}")
        print(f"  Policy status      : {results['crm_policy_status']}")
        if results["crm_annual_limit"] is not None:
            print(f"  Annual limit (EUR) : {results['crm_annual_limit']:,}")
        print(f"  Lookup field used  : {results['crm_lookup_field']}")
        print(f"  Eligible for intent: {results['crm_eligible']}")
        if results["crm_ineligibility"]:
            print(f"  Ineligibility note : {results['crm_ineligibility']}")

    # ── Stage 5: Response Generation ─────────────────────────────────────────
    print(f"\n  {dash}")
    print(f"  STAGE 5 — RESPONSE GENERATION (Claude 3 Sonnet)")
    print(f"  {dash}")
    print(f"  Confidence score: {results['confidence_score']:.4f}")
    print(f"  Action          : {results['action']}")
    print(f"  Final action    : {results['final_action'] or '(see action)'}")
    if results["response_text"]:
        print(f"\n  Generated response (first 600 chars):")
        wrapped = textwrap.fill(results["response_text"][:600], width=70,
                                initial_indent="    ", subsequent_indent="    ")
        print(wrapped)
        if len(results["response_text"]) > 600:
            print("    …")

    # ── Validation ────────────────────────────────────────────────────────────
    failures = validate_results(case, results)
    print(f"\n  {dash}")
    if failures:
        print(f"  VALIDATION: FAIL  ({len(failures)} check(s) failed)")
        for f in failures:
            print(f)
    else:
        print(f"  VALIDATION: PASS  (all expected outputs matched)")
    print(f"  {dash}")


# ══════════════════════════════════════════════════════════════════════════════
# Dry-run mode — preview payload without touching AWS
# ══════════════════════════════════════════════════════════════════════════════

def print_dry_run(case: Dict[str, Any], eml: str):
    bar  = "═" * 76
    dash = "─" * 76
    print(f"\n{bar}")
    print(f"  [DRY RUN]  {case['case_id']}")
    print(f"  {case['description']}")
    print(bar)

    print(f"\n  S3 upload target  : s3://{EMAIL_BUCKET}/{S3_PREFIX}/<run_id>/{case['case_id']}.eml")
    print(f"  State machine     : {STATE_MACHINE_ARN}")

    print(f"\n  Step Functions input payload:")
    print(f"    {{ \"bucket\": \"{EMAIL_BUCKET}\",")
    print(f"       \"key\":    \"{S3_PREFIX}/<run_id>/{case['case_id']}.eml\" }}")

    print(f"\n  MIME email preview ({len(eml)} bytes):")
    for line in eml.splitlines()[:20]:
        print(f"    {line}")
    if eml.count("\n") > 20:
        print("    …")

    print(f"\n  Expected outputs:")
    print(f"    intent       : {case['expected_intent']}")
    print(f"    policy_number: {case['expected_policy_num']}")
    print(f"    crm_found    : {case['expected_crm_found']}")
    print(f"    doc_category : {case['expected_doc_category']}")
    print(f"  {dash}")


# ══════════════════════════════════════════════════════════════════════════════
# Main runner
# ══════════════════════════════════════════════════════════════════════════════

def run_case(run_id: str, case: Dict[str, Any]) -> bool:
    """
    Execute one full pipeline run for the given test case.
    Returns True on SUCCEEDED + all validations passed.
    """
    print(f"\n  Building MIME email …")
    eml = build_mime_email(case)
    print(f"    Email size: {len(eml):,} bytes  (body + {case['attachment_filename']} attachment)")

    print(f"  Uploading to S3 …")
    s3_key = upload_email_to_s3(run_id, case, eml)

    print(f"  Starting Step Function execution …")
    exec_arn = start_execution(run_id, case["case_id"], s3_key)

    print(f"  Waiting for pipeline to complete (timeout={EXEC_TIMEOUT_SEC}s) …")
    exec_result = poll_execution(exec_arn, timeout=EXEC_TIMEOUT_SEC)

    results = extract_results(exec_result["output"])
    print_case_result(
        case=case,
        results=results,
        exec_arn=exec_arn,
        duration=exec_result["duration_sec"],
        status=exec_result["status"],
        error=exec_result.get("error"),
    )

    passed = (
        exec_result["status"] == "SUCCEEDED"
        and not validate_results(case, results)
    )
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="InsureMail AI — Step Function end-to-end demo"
    )
    parser.add_argument(
        "--case", type=int, choices=[1, 2],
        help="Run only case 1 or case 2 (default: both)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build payloads and print without triggering AWS",
    )
    parser.add_argument(
        "--timeout", type=int, default=EXEC_TIMEOUT_SEC,
        help=f"Per-execution timeout in seconds (default: {EXEC_TIMEOUT_SEC})",
    )
    args = parser.parse_args()

    # Select which cases to run
    cases_to_run = (
        [TEST_CASES[args.case - 1]] if args.case
        else TEST_CASES
    )

    bar = "═" * 76
    print(f"\n{bar}")
    print(f"  InsureMail AI — Step Function End-to-End Demo")
    print(f"  State machine : {STATE_MACHINE_ARN.split(':')[-1]}")
    print(f"  Email bucket  : {EMAIL_BUCKET}")
    print(f"  Region        : {REGION}")
    print(f"  Test cases    : {len(cases_to_run)}")
    print(f"  Mode          : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{bar}")

    if args.dry_run:
        for case in cases_to_run:
            eml = build_mime_email(case)
            print_dry_run(case, eml)
        return 0

    run_id  = uuid.uuid4().hex[:12]
    passed  = 0
    total   = len(cases_to_run)

    print(f"\n  Run ID: {run_id}\n")

    for i, case in enumerate(cases_to_run, 1):
        print(f"\n{'─'*76}")
        print(f"  [{i}/{total}] {case['case_id']}")
        print(f"  {case['description']}")
        print(f"{'─'*76}")
        ok = run_case(run_id, case)
        if ok:
            passed += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{bar}")
    print(f"  SUMMARY")
    print(f"  Passed: {passed}/{total}")
    print(f"  Result: {'PASS' if passed == total else 'FAIL'}")
    print(f"{bar}\n")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
