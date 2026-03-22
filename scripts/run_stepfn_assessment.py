#!/usr/bin/env python3
"""
InsureMail AI — Step Function Real-Pipeline Assessment
======================================================
Sends test emails through the LIVE AWS Step Function pipeline and scores the
pipeline's REAL outputs (intent, confidence, routing, response) against gold
labels from the Laya synthetic dataset.

Unlike run_e2e_assessment.py (which simulates locally using gold labels),
this script exercises every real Lambda end-to-end:
  email_parser (parse + entity extraction)
    → classify_intent_by_llm ∥ classify_intent_by_biobert (parallel)
    → rag_retrieval → crm_validation → llm_response

For each test email the script:
  1. Builds a raw RFC 2822 .eml string from the dataset record
  2. Uploads it to S3  (emails bucket)
  3. Starts a Step Function execution
  4. Polls until the execution succeeds / fails / times out
  5. Extracts the real predictions from the execution output
  6. Scores them against gold labels

Usage
-----
    # 20-email quick run (good for smoke-testing)
    python scripts/run_stepfn_assessment.py --sample 20

    # 50-email run with 5 concurrent executions (default)
    python scripts/run_stepfn_assessment.py --sample 50

    # Full 1000-email run
    python scripts/run_stepfn_assessment.py --sample 0 --concurrency 10

    # Custom email file (e.g., the curated 50-email e2e set)
    python scripts/run_stepfn_assessment.py \\
        --emails tests/test_data/e2e_test_emails.jsonl \\
        --sample 0

Output
------
- results/stepfn_assessment_YYYYMMDD_HHMMSS.json   (local)
- s3://insuremail-ai-dev-logs/assessment/latest.json  (S3, auto-uploaded)

Exit Codes
----------
0  — composite score >= PASS_THRESHOLD (0.70)
1  — below threshold, execution errors, or unrecoverable error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3

# ── TruLens (optional — only needed when --trulens flag is used) ───────────────
try:
    from trulens.providers.bedrock import Bedrock as TruLensBedrock
    TRULENS_AVAILABLE = True
except ImportError:
    TRULENS_AVAILABLE = False

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
DEFAULT_EMAILS = ROOT / "tests/test_data/laya_synthetic_dataset_starter/emails.jsonl"
DEFAULT_CASES  = ROOT / "tests/test_data/laya_synthetic_dataset_starter/cases.jsonl"
DEFAULT_DRAFTS = ROOT / "tests/test_data/laya_synthetic_dataset_starter/draft_responses.jsonl"

# ── AWS config (resolved from Terraform outputs or env) ───────────────────────

REGION             = os.environ.get("AWS_REGION",            "us-east-1")
EMAIL_BUCKET       = os.environ.get("EMAIL_BUCKET",          "insuremail-ai-dev-emails")
LOGS_BUCKET        = os.environ.get("RESULTS_BUCKET",        "insuremail-ai-dev-logs")
STATE_MACHINE_ARN  = os.environ.get("STATE_MACHINE_ARN",
    "arn:aws:states:us-east-1:970850578809:stateMachine:insuremail-ai-dev-email-processing")
EMAIL_TABLE_NAME   = os.environ.get("EMAIL_TABLE_NAME",      "insuremail-ai-dev-email-processing")

# ── Assessment config ─────────────────────────────────────────────────────────

PASS_THRESHOLD      = 0.70
EXEC_TIMEOUT_SEC    = 120     # max seconds to wait for one execution
TRULENS_MODEL_ID    = "anthropic.claude-3-haiku-20240307-v1:0"
TRULENS_WORKERS     = 5       # parallel TruLens scoring calls
POLL_INTERVAL_SEC   = 3       # seconds between status polls
S3_PREFIX           = "test-pipeline"   # S3 key prefix for uploaded emails

INTENT_TO_ROUTE = {
    "coverage_query":           "customer_support_team",
    "claim_submission":         "claims_team",
    "claim_status":             "claims_team",
    "claim_reimbursement_query":"claims_team",
    "pre_authorisation":        "medical_review_team",
    "payment_issue":            "finance_support_team",
    "policy_change":            "policy_admin_team",
    "renewal_query":            "renewals_team",
    "cancellation_request":     "retention_team",
    "enrollment_new_policy":    "sales_enrollment_team",
    "dependent_addition":       "policy_admin_team",
    "complaint":                "complaints_team",
    "document_followup":        "operations_team",
    "hospital_network_query":   "provider_support_team",
    "id_verification":          "operations_team",
    "broker_query":             "general_support_team",
    "other":                    "general_support_team",
}

# ── AWS clients ───────────────────────────────────────────────────────────────

sfn_client     = boto3.client("stepfunctions",  region_name=REGION)
s3_client      = boto3.client("s3",             region_name=REGION)
lambda_client  = boto3.client("lambda",         region_name=REGION)
dynamo         = boto3.resource("dynamodb",     region_name=REGION)
email_table    = dynamo.Table(EMAIL_TABLE_NAME)

BIOBERT_LAMBDA = os.environ.get("BIOBERT_LAMBDA", "insuremail-ai-dev-sagemaker-inference")

# ── Data loading ──────────────────────────────────────────────────────────────

def _load_jsonl(path: Path) -> List[Dict]:
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_dataset(emails_path: Path, cases_path: Optional[Path],
                 sample: Optional[int]) -> Tuple[List[Dict], Dict[str, Dict]]:
    emails = _load_jsonl(emails_path)
    if sample and sample > 0:
        emails = emails[:sample]

    cases: Dict[str, Dict] = {}
    if cases_path and cases_path.exists():
        for c in _load_jsonl(cases_path):
            cases[c["email_id"]] = c

    return emails, cases


# ── RFC 2822 email construction ───────────────────────────────────────────────

def build_eml(record: Dict) -> str:
    """Convert a laya dataset email record into a raw RFC 2822 .eml string."""
    sender_name  = record.get("sender_name", "Customer")
    sender_email = record.get("sender_email", f"customer+{record['email_id'][:8]}@example.com")
    subject      = record.get("subject", "(no subject)")
    body_text    = record.get("body_text", record.get("body", ""))
    received_at  = record.get("received_at", datetime.now(timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S +0000"))

    msg = MIMEText(body_text, "plain", "utf-8")
    msg["From"]       = f"{sender_name} <{sender_email}>"
    msg["To"]         = "support@insuremail.ie"
    msg["Subject"]    = subject
    msg["Date"]       = received_at
    msg["Message-ID"] = f"<{record['email_id']}@eval.insuremail.ie>"
    return msg.as_string()


# ── S3 upload ─────────────────────────────────────────────────────────────────

def upload_email(run_id: str, laya_email_id: str, eml_content: str) -> str:
    """Upload raw email to S3, return the S3 key."""
    key = f"{S3_PREFIX}/{run_id}/{laya_email_id}.eml"
    s3_client.put_object(
        Bucket=EMAIL_BUCKET,
        Key=key,
        Body=eml_content.encode("utf-8"),
        ContentType="message/rfc822",
    )
    return key


# ── Step Function trigger + poll ──────────────────────────────────────────────

def start_execution(laya_email_id: str, s3_key: str, run_id: str) -> str:
    """Start a Step Function execution; return its ARN."""
    name = f"eval-{laya_email_id[:12]}-{run_id[:8]}"
    # execution names must be ≤80 chars and [a-zA-Z0-9_-]
    name = name.replace("_", "-")[:80]
    resp = sfn_client.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=name,
        input=json.dumps({"bucket": EMAIL_BUCKET, "key": s3_key}),
    )
    return resp["executionArn"]


def poll_execution(exec_arn: str, timeout: int = EXEC_TIMEOUT_SEC) -> Dict:
    """
    Poll until execution reaches a terminal state.
    Returns a dict with status, output (parsed), error.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp   = sfn_client.describe_execution(executionArn=exec_arn)
        status = resp["status"]           # RUNNING | SUCCEEDED | FAILED | TIMED_OUT | ABORTED

        if status == "SUCCEEDED":
            output = json.loads(resp.get("output", "{}"))
            return {"status": "SUCCEEDED", "output": output, "error": None}

        if status in ("FAILED", "TIMED_OUT", "ABORTED"):
            cause = resp.get("cause", "")
            error = resp.get("error", status)
            return {"status": status, "output": {}, "error": f"{error}: {cause[:200]}"}

        time.sleep(POLL_INTERVAL_SEC)

    # Timeout from our side — stop the execution
    try:
        sfn_client.stop_execution(executionArn=exec_arn, cause="eval-timeout")
    except Exception:
        pass
    return {"status": "EVAL_TIMEOUT", "output": {}, "error": f"Exceeded {timeout}s eval timeout"}


# ── Output extraction ─────────────────────────────────────────────────────────

def extract_pipeline_result(laya_record: Dict, exec_result: Dict) -> Dict:
    """
    Extract prediction fields from a completed Step Function execution output.
    Returns a flat dict suitable for scoring.
    """
    out = exec_result.get("output", {})

    # ── predicted intent ─────────────────────────────────────────────────────
    # Supports both state machine versions:
    #   New (after tf-apply): $.classifiers[0].llm_result.classification
    #   Legacy (deployed):    $.analysis[0].intent.classification
    clf = {}
    try:
        clf = out["classifiers"][0]["llm_result"]["classification"]
    except (KeyError, IndexError, TypeError):
        pass
    if not clf:
        try:
            clf = out["analysis"][0]["intent"]["classification"]
        except (KeyError, IndexError, TypeError):
            pass

    predicted_intent    = clf.get("customer_intent", "other")
    predicted_urgency   = clf.get("urgency", "")
    predicted_sentiment = clf.get("sentiment", "")
    predicted_route     = clf.get("gold_route_team") or INTENT_TO_ROUTE.get(predicted_intent, "general_support_team")

    # ── BioBERT intent (from classify_intent_by_biobert — $.classifiers[1].biobert_result)
    # After tf-apply: read from Step Functions output.
    # Before tf-apply (legacy state machine): invoke the Lambda directly as fallback.
    biobert_clf = {}
    try:
        biobert_clf = out["classifiers"][1].get("biobert_result", {})
    except (KeyError, IndexError, TypeError):
        pass
    if not biobert_clf:
        body_text = laya_record.get("body_text", laya_record.get("body", ""))
        if body_text:
            try:
                # Lambda is an API Gateway handler — pass event with "body" key
                raw = lambda_client.invoke(
                    FunctionName=BIOBERT_LAMBDA,
                    InvocationType="RequestResponse",
                    Payload=json.dumps({"body": json.dumps({"text": body_text[:2000]})}).encode(),
                )
                lambda_resp = json.loads(raw["Payload"].read())
                payload = json.loads(lambda_resp.get("body", "{}"))
                pred = (payload.get("predictions") or [{}])[0]
                if pred.get("intent"):
                    biobert_clf = {
                        "classification": {"customer_intent": pred["intent"]},
                        "confidence":     pred.get("score", 0.0),
                        "model":          "biobert-finetuned",
                        "all_scores":     pred.get("all_scores", {}),
                    }
            except Exception:
                pass
    biobert_intent     = (biobert_clf.get("classification") or {}).get("customer_intent", "")
    biobert_confidence = float(biobert_clf.get("confidence", 0.0))
    biobert_model      = biobert_clf.get("model", "")

    # ── response + confidence (from llm_response Lambda) ────────────────
    resp = out.get("response", {})
    confidence_score = float(resp.get("confidence_score", 0.0))
    action           = resp.get("action", "escalate")
    response_text    = resp.get("response_text", "")

    # ── RAG (from rag_retrieval Lambda) ────────────────────────────────────
    rag_docs      = out.get("rag_results", {}).get("retrieved_documents", [])
    rag_hit_count = len(rag_docs)

    # ── CRM validation (from crm_validation Lambda, ResultPath=$.crm_validation)
    crm           = out.get("crm_validation", {})
    crm_found     = bool(crm.get("crm_found", False))
    crm_policy    = crm.get("policy") or {}
    crm_validation_block = crm.get("validation") or {}

    # ── parsed email entities (from email_parser — inline Textract + Claude extraction)
    parsed = out.get("parsed_email", {}).get("parsed_data", {})
    extracted_policy = parsed.get("policy_number", "")
    extracted_member = parsed.get("member_id", "")
    pii_detected     = bool(parsed.get("pii_present", False))
    medical_detected = bool(parsed.get("medical_terms_present", False))
    # Bedrock entity extraction confidence (stored under parsed_data['entities'])
    entities_block   = parsed.get("entities", {})
    entity_confidence = float(entities_block.get("extraction_confidence", 0.0)) if entities_block else 0.0

    # Build RAG context string for TruLens scoring (joined doc snippets)
    rag_context_str = "\n\n".join(
        d.get("content", "")[:600] for d in rag_docs[:5]
    ) or "No documents retrieved."

    return {
        "laya_email_id":      laya_record["email_id"],
        "sfn_email_id":       out.get("parsed_email", {}).get("email_id", ""),
        "gold_intent":        laya_record.get("customer_intent", ""),
        "gold_route_team":    laya_record.get("gold_route_team", ""),
        "gold_requires_human":laya_record.get("requires_human_review", False),
        # ── LLM classifier (authoritative)
        "predicted_intent":   predicted_intent,
        "predicted_urgency":  predicted_urgency,
        "predicted_sentiment":predicted_sentiment,
        "predicted_route":    predicted_route,
        # ── BioBERT classifier (parallel branch, for comparison)
        "biobert_intent":     biobert_intent,
        "biobert_confidence": biobert_confidence,
        "biobert_model":      biobert_model,
        "classifiers_agree":  predicted_intent == biobert_intent if biobert_intent else None,
        # ── Response
        "confidence_score":   confidence_score,
        "action":             action,
        "response_text":      response_text[:500],   # truncate for report size
        "rag_hit_count":      rag_hit_count,
        # ── CRM validation
        "crm_found":          crm_found,
        "crm_policy_status":  crm_policy.get("policy_status", ""),
        "crm_plan_name":      crm_policy.get("plan_name", ""),
        "crm_eligible":       crm_validation_block.get("eligible_for_intent"),
        # ── Entity extraction (email_parser inline Textract + Claude)
        "extracted_policy":   extracted_policy,
        "extracted_member":   extracted_member,
        "pii_detected":       pii_detected,
        "medical_detected":   medical_detected,
        "entity_confidence":  entity_confidence,
        "exec_status":        exec_result["status"],
        "exec_error":         exec_result.get("error"),
        # ── TruLens inputs (stripped before saving to report) ──────────────
        "_question":     f"Subject: {laya_record.get('subject','')}\n{laya_record.get('body_text','')}",
        "_rag_context":  rag_context_str,
        "_full_response": response_text,
    }


# ── Per-email runner (runs in thread pool) ────────────────────────────────────

def run_one(run_id: str, laya_record: Dict) -> Dict:
    laya_id = laya_record["email_id"]
    try:
        eml   = build_eml(laya_record)
        key   = upload_email(run_id, laya_id, eml)
        arn   = start_execution(laya_id, key, run_id)
        result = poll_execution(arn)
        return extract_pipeline_result(laya_record, result)
    except Exception as exc:
        return {
            "laya_email_id":      laya_id,
            "sfn_email_id":       "",
            "gold_intent":        laya_record.get("customer_intent", ""),
            "gold_route_team":    laya_record.get("gold_route_team", ""),
            "gold_requires_human":laya_record.get("requires_human_review", False),
            "predicted_intent":   "other",
            "predicted_urgency":  "",
            "predicted_sentiment":"",
            "predicted_route":    "general_support_team",
            "biobert_intent":     "",
            "biobert_confidence": 0.0,
            "biobert_model":      "",
            "classifiers_agree":  None,
            "confidence_score":   0.0,
            "action":             "escalate",
            "response_text":      "",
            "rag_hit_count":      0,
            "crm_found":          False,
            "crm_policy_status":  "",
            "crm_plan_name":      "",
            "crm_eligible":       None,
            "extracted_policy":   "",
            "extracted_member":   "",
            "pii_detected":       False,
            "medical_detected":   False,
            "entity_confidence":  0.0,
            "exec_status":        "EXCEPTION",
            "exec_error":         str(exc)[:300],
        }


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_intent(results: List[Dict]) -> Dict:
    correct = sum(1 for r in results if r["predicted_intent"] == r["gold_intent"])
    total   = len(results)
    accuracy = correct / total if total else 0.0

    per_class: Dict[str, Dict] = {}
    for r in results:
        g = r["gold_intent"]
        p = r["predicted_intent"]
        if g not in per_class:
            per_class[g] = {"tp": 0, "fp": 0, "fn": 0, "support": 0}
        per_class[g]["support"] += 1
        if g == p:
            per_class[g]["tp"] += 1
        else:
            per_class[g]["fn"] += 1
            per_class.setdefault(p, {"tp": 0, "fp": 0, "fn": 0, "support": 0})
            per_class[p]["fp"] += 1

    per_class_scores = {}
    for intent, counts in per_class.items():
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec  = tp / (tp + fn) if (tp + fn) else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class_scores[intent] = {"precision": round(prec, 4), "recall": round(rec, 4),
                                     "f1": round(f1, 4), "support": counts["support"]}

    f1s = [v["f1"] for v in per_class_scores.values()]
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0

    # Top confused pairs
    confused = Counter(
        (r["gold_intent"], r["predicted_intent"])
        for r in results if r["predicted_intent"] != r["gold_intent"]
    )
    top_confused = [
        {"true": g, "predicted": p, "count": c}
        for (g, p), c in confused.most_common(5)
    ]

    return {
        "accuracy":    round(accuracy, 4),
        "macro_f1":    round(macro_f1, 4),
        "weighted_f1": round(macro_f1, 4),   # approximation without sklearn
        "per_class":   per_class_scores,
        "top_confused":top_confused,
        "n_samples":   total,
        "n_correct":   correct,
    }


def score_routing(results: List[Dict]) -> Dict:
    correct = sum(1 for r in results
                  if r["predicted_route"].lower() == r["gold_route_team"].lower())
    total   = len(results)
    per_team: Dict[str, Dict] = {}
    for r in results:
        t = r["gold_route_team"]
        per_team.setdefault(t, {"correct": 0, "total": 0})
        per_team[t]["total"] += 1
        if r["predicted_route"].lower() == t.lower():
            per_team[t]["correct"] += 1

    return {
        "routing_accuracy": round(correct / total, 4) if total else 0.0,
        "correct":          correct,
        "total":            total,
        "per_team":         {t: round(v["correct"] / v["total"], 4) if v["total"] else 0.0
                              for t, v in per_team.items()},
    }


def score_confidence(results: List[Dict]) -> Dict:
    scores  = [r["confidence_score"] for r in results]
    correct = [1 if r["predicted_intent"] == r["gold_intent"] else 0 for r in results]

    # Routing distribution
    action_counts: Counter = Counter(r["action"] for r in results)
    n = len(results) or 1
    routing_dist = {a: round(c / n, 4) for a, c in action_counts.items()}

    # ECE (10 bins)
    bins = 10
    bin_stats = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idxs = [j for j, s in enumerate(scores) if lo <= s < hi]
        if not idxs:
            continue
        avg_conf = sum(scores[j] for j in idxs) / len(idxs)
        avg_acc  = sum(correct[j] for j in idxs) / len(idxs)
        bin_stats.append({"bin_lower": lo, "bin_upper": hi,
                          "avg_confidence": round(avg_conf, 4),
                          "avg_accuracy":   round(avg_acc, 4),
                          "n": len(idxs)})

    ece = sum(b["n"] * abs(b["avg_confidence"] - b["avg_accuracy"])
              for b in bin_stats) / n if bin_stats else 0.0

    # human_review agreement
    human_needed    = [r for r in results if r.get("gold_requires_human")]
    predicted_review = [r for r in human_needed if r["action"] in ("human_review", "escalate")]
    escalation_agreement = (len(predicted_review) / len(human_needed)
                            if human_needed else None)

    return {
        "ece":              round(ece, 4),
        "mae_vs_band":      0.0,   # not applicable without band labels
        "band_action_agreement": round(escalation_agreement, 4) if escalation_agreement is not None else None,
        "routing_distribution": routing_dist,
        "routing_counts":   dict(action_counts),
        "reliability_diagram": bin_stats,
    }


def score_rag(results: List[Dict], cases: Dict[str, Dict]) -> Dict:
    hits  = [r for r in results if r["rag_hit_count"] > 0]
    total = len(results)
    hit_rate = len(hits) / total if total else 0.0

    return {
        "hit_rate":  round(hit_rate, 4),
        "mrr":       round(hit_rate, 4),   # approximation: hit = relevant doc at rank 1
        "ndcg_at_5": round(hit_rate, 4),
        "hits":      len(hits),
        "total":     total,
        "avg_docs_retrieved": round(
            sum(r["rag_hit_count"] for r in results) / total, 2) if total else 0.0,
    }


def score_response(results: List[Dict]) -> Dict:
    hedge_phrases = ["please", "kindly", "if you have", "do not hesitate",
                     "thank you", "we understand", "we apologise", "we apologize",
                     "feel free", "should you", "for your convenience"]
    responses_with_text = [r for r in results if r.get("response_text")]
    hedge_rate = (
        sum(1 for r in responses_with_text
            if any(ph in r["response_text"].lower() for ph in hedge_phrases))
        / len(responses_with_text)
    ) if responses_with_text else 0.0

    human_needed = [r for r in results if r.get("gold_requires_human")]
    predicted_escalate = [r for r in human_needed if r["action"] in ("human_review", "escalate")]
    escalation_agreement = (
        len(predicted_escalate) / len(human_needed) if human_needed else None
    )

    return {
        "avg_rouge_l":           None,
        "rouge_l_coverage":      0.0,
        "hedge_rate":            round(hedge_rate, 4),
        "escalation_agreement":  round(escalation_agreement, 4) if escalation_agreement is not None else None,
        "escalation_pairs_evaluated": len(human_needed),
        "n_with_response":       len(responses_with_text),
    }


def score_biobert(results: List[Dict]) -> Dict:
    """Agreement between LLM and BioBERT classifiers on this sample."""
    comparable = [r for r in results if r.get("biobert_intent")]
    if not comparable:
        return {"available": False, "n_compared": 0}

    agree = sum(1 for r in comparable if r.get("classifiers_agree"))
    agreement_rate = agree / len(comparable)

    # BioBERT accuracy against gold labels (independent of LLM)
    biobert_correct = sum(
        1 for r in comparable if r.get("biobert_intent") == r.get("gold_intent")
    )
    biobert_accuracy = biobert_correct / len(comparable)

    avg_confidence = sum(r.get("biobert_confidence", 0.0) for r in comparable) / len(comparable)

    return {
        "available":        True,
        "n_compared":       len(comparable),
        "agreement_rate":   round(agreement_rate, 4),
        "biobert_accuracy": round(biobert_accuracy, 4),
        "avg_confidence":   round(avg_confidence, 4),
        "agree_count":      agree,
    }


def score_crm(results: List[Dict]) -> Dict:
    """CRM lookup hit rate and policy status distribution across the sample."""
    total     = len(results)
    hits      = sum(1 for r in results if r.get("crm_found"))
    eligible  = sum(1 for r in results if r.get("crm_eligible") is True)
    hit_rate  = hits / total if total else 0.0

    status_counts: Counter = Counter(
        r.get("crm_policy_status", "") for r in results if r.get("crm_found")
    )
    plan_counts: Counter = Counter(
        r.get("crm_plan_name", "") for r in results if r.get("crm_found")
    )

    return {
        "hit_rate":        round(hit_rate, 4),
        "hits":            hits,
        "total":           total,
        "eligible":        eligible,
        "status_counts":   dict(status_counts),
        "plan_counts":     dict(plan_counts),
    }


def score_entity(results: List[Dict], gold_records: List[Dict]) -> Dict:
    gold_has_policy = [bool(r.get("policy_number")) for r in gold_records]
    pred_has_policy = [bool(r.get("extracted_policy")) for r in results]

    def _prf(gold_flags, pred_flags):
        tp = sum(1 for g, p in zip(gold_flags, pred_flags) if g and p)
        fp = sum(1 for g, p in zip(gold_flags, pred_flags) if not g and p)
        fn = sum(1 for g, p in zip(gold_flags, pred_flags) if g and not p)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec  = tp / (tp + fn) if (tp + fn) else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        return {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}

    gold_has_member = [bool(r.get("member_id")) for r in gold_records]
    pred_has_member = [bool(r.get("extracted_member")) for r in results]

    gold_pii = [bool(r.get("pii_present")) for r in gold_records]
    pred_pii = [r.get("pii_detected", False) for r in results]

    gold_med = [bool(r.get("medical_terms_present")) for r in gold_records]
    pred_med = [r.get("medical_detected", False) for r in results]

    return {
        "policy_number": _prf(gold_has_policy, pred_has_policy),
        "member_id":     _prf(gold_has_member,  pred_has_member),
        "pii_flag":      _prf(gold_pii,          pred_pii),
        "medical_flag":  _prf(gold_med,          pred_med),
    }


# ── TruLens RAG Triad scoring ─────────────────────────────────────────────────

def _score_one_trulens(args: Tuple) -> Dict:
    """Score a single email with TruLens RAG triad. Runs in a thread."""
    provider, laya_id, question, context, response = args
    scores: Dict[str, Any] = {"laya_email_id": laya_id}

    def _safe(fn, **kwargs) -> float:
        try:
            result = fn(**kwargs)
            # groundedness returns Tuple[float, Dict]; others return float
            val = result[0] if isinstance(result, tuple) else result
            return round(float(val), 4)
        except Exception as exc:
            print(f"    [TruLens] {fn.__name__} failed for {laya_id[:12]}: {exc}")
            return None

    scores["answer_relevance"]  = _safe(provider.relevance,
                                        prompt=question, response=response)
    scores["context_relevance"] = _safe(provider.context_relevance,
                                        question=question, context=context)
    scores["groundedness"]      = _safe(provider.groundedness_measure_with_cot_reasons,
                                        source=context, statement=response)

    valid = [v for v in [scores["answer_relevance"],
                         scores["context_relevance"],
                         scores["groundedness"]] if v is not None]
    scores["triad_avg"] = round(sum(valid) / len(valid), 4) if valid else None
    return scores


def score_trulens_rag_triad(results: List[Dict]) -> Optional[Dict]:
    """
    Run TruLens RAG Triad evaluation on all emails that have a response.
    Returns aggregate + per-email scores, or None if TruLens is unavailable.
    """
    if not TRULENS_AVAILABLE:
        print("[TruLens] Package not installed. Run: pip install trulens-providers-bedrock")
        return None

    scoreable = [
        r for r in results
        if r.get("_full_response") and r.get("exec_status") == "SUCCEEDED"
    ]
    if not scoreable:
        return None

    print(f"\nRunning TruLens RAG Triad on {len(scoreable)} emails "
          f"(model={TRULENS_MODEL_ID})...")

    try:
        provider = TruLensBedrock(model_id=TRULENS_MODEL_ID)
    except Exception as exc:
        print(f"[TruLens] Provider init failed: {exc}")
        return None

    tasks = [
        (provider,
         r["laya_email_id"],
         r["_question"],
         r["_rag_context"],
         r["_full_response"])
        for r in scoreable
    ]

    per_email: List[Dict] = []
    n_done = 0
    with ThreadPoolExecutor(max_workers=TRULENS_WORKERS) as pool:
        futures = {pool.submit(_score_one_trulens, t): t for t in tasks}
        for future in as_completed(futures):
            row = future.result()
            per_email.append(row)
            n_done += 1
            avg = row.get("triad_avg")
            avg_str = f"{avg:.4f}" if avg is not None else "err"
            print(f"  [{n_done:>3}/{len(scoreable)}] {row['laya_email_id'][:20]:<20} "
                  f"AR={row.get('answer_relevance','?')}  "
                  f"CR={row.get('context_relevance','?')}  "
                  f"GR={row.get('groundedness','?')}  "
                  f"avg={avg_str}")

    def _avg_metric(key: str) -> Optional[float]:
        vals = [r[key] for r in per_email if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    agg = {
        "avg_answer_relevance":  _avg_metric("answer_relevance"),
        "avg_context_relevance": _avg_metric("context_relevance"),
        "avg_groundedness":      _avg_metric("groundedness"),
        "avg_triad":             _avg_metric("triad_avg"),
        "n_evaluated":           len(scoreable),
        "provider_model":        TRULENS_MODEL_ID,
        "per_email":             per_email,
    }
    print(f"\n  TruLens summary — "
          f"AnswerRelevance={agg['avg_answer_relevance']}  "
          f"ContextRelevance={agg['avg_context_relevance']}  "
          f"Groundedness={agg['avg_groundedness']}  "
          f"Triad={agg['avg_triad']}")
    return agg


# ── Composite score ───────────────────────────────────────────────────────────

def compute_composite(intent_m, routing_m, entity_m, rag_m, crm_m, response_m, calib_m,
                      biobert_m=None, trulens_m=None) -> float:
    scores = []
    scores.append(intent_m["accuracy"])
    scores.append(routing_m["routing_accuracy"])
    scores.append(entity_m["policy_number"]["f1"])
    scores.append(rag_m["hit_rate"])
    scores.append(crm_m["hit_rate"])
    if calib_m["band_action_agreement"] is not None:
        scores.append(calib_m["band_action_agreement"])
    ece_score = max(0.0, 1.0 - calib_m["ece"] * 2)
    scores.append(ece_score)
    # Include TruLens triad average when available
    if trulens_m and trulens_m.get("avg_triad") is not None:
        scores.append(trulens_m["avg_triad"])
    return round(sum(scores) / len(scores), 4) if scores else 0.0


# ── Report ────────────────────────────────────────────────────────────────────

def _strip_trulens_inputs(results: List[Dict]) -> List[Dict]:
    """Remove _question/_rag_context/_full_response fields before saving."""
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]


def build_report(emails, results, cases, intent_m, routing_m, entity_m,
                 rag_m, crm_m, response_m, calib_m, elapsed: float, run_id: str,
                 biobert_m=None, trulens_m=None) -> Dict:
    composite = compute_composite(intent_m, routing_m, entity_m, rag_m, crm_m,
                                  response_m, calib_m, biobert_m, trulens_m)
    passed    = composite >= PASS_THRESHOLD
    n_failed  = sum(1 for r in results if r["exec_status"] != "SUCCEEDED")

    dimensions = {
        "intent_classification":  intent_m,
        "routing_accuracy":       routing_m,
        "entity_extraction":      entity_m,
        "rag_retrieval":          rag_m,
        "crm_validation":         crm_m,
        "response_quality":       response_m,
        "confidence_calibration": calib_m,
    }
    if biobert_m:
        dimensions["biobert_vs_llm"] = biobert_m
    if trulens_m:
        # Store aggregate + per-email (without the raw text inputs)
        trulens_stored = {k: v for k, v in trulens_m.items() if k != "per_email"}
        trulens_stored["per_email"] = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in trulens_m.get("per_email", [])
        ]
        dimensions["trulens_rag_triad"] = trulens_stored

    return {
        "assessment_metadata": {
            "source":            "step_functions",
            "run_id":            run_id,
            "generated_at":      datetime.now(timezone.utc).isoformat(),
            "n_emails":          len(emails),
            "n_succeeded":       len(results) - n_failed,
            "n_failed_exec":     n_failed,
            "dry_run":           False,
            "elapsed_seconds":   round(elapsed, 1),
            "state_machine_arn": STATE_MACHINE_ARN,
            "email_bucket":      EMAIL_BUCKET,
            "pass_threshold":    PASS_THRESHOLD,
            "passed":            passed,
            "trulens_enabled":   trulens_m is not None,
        },
        "composite_score":  composite,
        "dimensions":       dimensions,
        "per_email_results": _strip_trulens_inputs(results[:200]),
    }


def print_report(report: Dict):
    meta = report["assessment_metadata"]
    dims = report["dimensions"]
    composite = report["composite_score"]
    passed    = meta["passed"]

    bar = "=" * 72
    print(f"\n{bar}")
    print("  INSUREMAIL AI — STEP FUNCTION PIPELINE ASSESSMENT")
    print(f"  Run ID:   {meta['run_id']}")
    print(f"  Generated: {meta['generated_at']}")
    print(f"  Emails:   {meta['n_emails']}  |  Succeeded: {meta['n_succeeded']}  |  Failed: {meta['n_failed_exec']}")
    print(f"  Elapsed:  {meta['elapsed_seconds']}s")
    print(bar)

    status = "PASSED" if passed else "FAILED"
    print(f"\n  COMPOSITE SCORE: {composite:.4f}  [{status}]  (threshold={PASS_THRESHOLD})")

    sections = [
        ("INTENT CLASSIFICATION", "intent_classification",
         lambda d: [f"  Accuracy:    {d['accuracy']:.4f}", f"  Macro F1:    {d['macro_f1']:.4f}",
                    f"  Samples:     {d['n_samples']}  |  Correct: {d['n_correct']}"]),
        ("ROUTING ACCURACY",      "routing_accuracy",
         lambda d: [f"  Accuracy:    {d['routing_accuracy']:.4f}  ({d['correct']}/{d['total']})"]),
        ("ENTITY EXTRACTION",     "entity_extraction",
         lambda d: [f"  Policy P/R/F1: {d['policy_number']['precision']:.4f} / "
                     f"{d['policy_number']['recall']:.4f} / {d['policy_number']['f1']:.4f}",
                    f"  PII Flag F1:   {d['pii_flag']['f1']:.4f}"]),
        ("RAG RETRIEVAL",         "rag_retrieval",
         lambda d: [f"  Hit rate: {d['hit_rate']:.4f}  ({d['hits']}/{d['total']})",
                    f"  Avg docs retrieved: {d['avg_docs_retrieved']:.1f}"]),
        ("CRM VALIDATION",        "crm_validation",
         lambda d: [f"  CRM hit rate:  {d['hit_rate']:.4f}  ({d['hits']}/{d['total']})",
                    f"  Eligible:      {d['eligible']}",
                    *[f"    {k:<12} {v}" for k, v in d["status_counts"].items()]]),
        ("RESPONSE QUALITY",      "response_quality",
         lambda d: [f"  Hedge rate:             {d['hedge_rate']:.4f}",
                    f"  Escalation agreement:   "
                    f"{d['escalation_agreement']:.4f}" if d['escalation_agreement'] is not None
                    else "  Escalation agreement:   N/A",
                    f"  Responses generated:    {d['n_with_response']}"]),
        ("CONFIDENCE CALIBRATION","confidence_calibration",
         lambda d: [f"  ECE: {d['ece']:.4f}",
                    *[f"    {k:<20} {v:.4f}  ({d['routing_counts'].get(k,0)} emails)"
                      for k, v in d["routing_distribution"].items()]]),
    ]

    for title, key, fmt in sections:
        print(f"\n{'-'*72}")
        print(f"  STAGE — {title}")
        print(f"{'-'*72}")
        for line in fmt(dims[key]):
            print(line)

    n_confused = dims["intent_classification"].get("top_confused", [])
    if n_confused:
        print(f"\n  Top confused pairs:")
        for pair in n_confused[:5]:
            print(f"    {pair['true']:<35} → {pair['predicted']:<35} (n={pair['count']})")

    if "biobert_vs_llm" in dims:
        b = dims["biobert_vs_llm"]
        print(f"\n{'-'*72}")
        print(f"  STAGE — BIOBERT vs LLM CLASSIFIER COMPARISON")
        print(f"{'-'*72}")
        if b.get("available"):
            print(f"  BioBERT accuracy (vs gold): {b['biobert_accuracy']:.4f}")
            print(f"  LLM–BioBERT agreement:      {b['agreement_rate']:.4f}  ({b['agree_count']}/{b['n_compared']})")
            print(f"  BioBERT avg confidence:     {b['avg_confidence']:.4f}")
        else:
            print("  BioBERT endpoint unavailable — no comparison data")

    if "trulens_rag_triad" in dims:
        t = dims["trulens_rag_triad"]
        print(f"\n{'-'*72}")
        print(f"  STAGE — TRULENS RAG TRIAD  (n={t.get('n_evaluated')} emails, model=haiku)")
        print(f"{'-'*72}")
        ar = t.get('avg_answer_relevance')
        cr = t.get('avg_context_relevance')
        gr = t.get('avg_groundedness')
        av = t.get('avg_triad')
        print(f"  Answer Relevance:   {ar:.4f}" if ar is not None else "  Answer Relevance:   N/A")
        print(f"  Context Relevance:  {cr:.4f}" if cr is not None else "  Context Relevance:  N/A")
        print(f"  Groundedness:       {gr:.4f}" if gr is not None else "  Groundedness:       N/A")
        print(f"  Triad Average:      {av:.4f}" if av is not None else "  Triad Average:      N/A")

    print(f"\n{bar}")
    trulens_note = "  (TruLens triad included in composite)\n" if "trulens_rag_triad" in dims else ""
    print(f"  RESULT: {'PASSED' if passed else 'FAILED'}  |  Composite={composite:.4f}  |  Threshold={PASS_THRESHOLD}")
    if trulens_note:
        print(trulens_note, end="")
    print(f"{bar}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="InsureMail AI Step Function pipeline assessment")
    p.add_argument("--emails",      type=Path, default=DEFAULT_EMAILS)
    p.add_argument("--cases",       type=Path, default=DEFAULT_CASES)
    p.add_argument("--sample",      type=int,  default=50,
                   help="Number of emails (0 = all)")
    p.add_argument("--concurrency", type=int,  default=5,
                   help="Max concurrent Step Function executions")
    p.add_argument("--timeout",     type=int,  default=EXEC_TIMEOUT_SEC,
                   help="Per-execution timeout in seconds")
    p.add_argument("--output",      type=Path, default=None)
    p.add_argument("--trulens",     action="store_true", default=False,
                   help="Run TruLens RAG Triad evaluation after pipeline (adds latency)")
    return p.parse_args()


def main() -> int:
    args   = parse_args()
    t0     = time.monotonic()
    run_id = uuid.uuid4().hex[:12]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.output is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output = RESULTS_DIR / f"stepfn_assessment_{ts}.json"

    print(f"InsureMail AI — Step Function Assessment  (run_id={run_id})")
    print(f"  State machine: {STATE_MACHINE_ARN}")
    print(f"  Email bucket:  {EMAIL_BUCKET}")
    print(f"  Sample size:   {'all' if not args.sample else args.sample}")
    print(f"  Concurrency:   {args.concurrency}")
    print(f"  Timeout/exec:  {args.timeout}s")
    print(f"  Output:        {args.output}\n")

    # ── Load dataset ──────────────────────────────────────────────────────────
    emails, cases = load_dataset(args.emails, args.cases,
                                 args.sample if args.sample > 0 else None)
    print(f"Loaded {len(emails)} emails, {len(cases)} cases.\n")

    # ── Run pipeline concurrently ─────────────────────────────────────────────
    results: List[Dict] = []
    n_done  = 0
    n_total = len(emails)

    print(f"Triggering Step Function executions (concurrency={args.concurrency})...")
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        future_to_email = {
            pool.submit(run_one, run_id, email): email
            for email in emails
        }
        for future in as_completed(future_to_email):
            result = future.result()
            results.append(result)
            n_done += 1
            status_icon = "✓" if result["exec_status"] == "SUCCEEDED" else "✗"
            print(f"  [{n_done:>4}/{n_total}] {status_icon} {result['laya_email_id'][:20]:<20} "
                  f"pred={result['predicted_intent']:<25} "
                  f"gold={result['gold_intent']:<25} "
                  f"conf={result['confidence_score']:.3f} "
                  f"action={result['action']}")

    print(f"\nAll executions complete. Computing metrics...")

    # ── Score ─────────────────────────────────────────────────────────────────
    succeeded = [r for r in results if r["exec_status"] == "SUCCEEDED"]
    if not succeeded:
        print("[ERROR] No successful executions. Check Lambda logs.", file=sys.stderr)
        return 1

    # Build aligned gold records list for entity scoring
    gold_map = {e["email_id"]: e for e in emails}
    gold_records = [gold_map[r["laya_email_id"]] for r in succeeded if r["laya_email_id"] in gold_map]

    intent_m   = score_intent(succeeded)
    routing_m  = score_routing(succeeded)
    entity_m   = score_entity(succeeded, gold_records)
    rag_m      = score_rag(succeeded, cases)
    crm_m      = score_crm(succeeded)
    response_m = score_response(succeeded)
    calib_m    = score_confidence(succeeded)
    biobert_m  = score_biobert(succeeded)

    # ── TruLens RAG Triad (optional) ──────────────────────────────────────────
    trulens_m = None
    if args.trulens:
        if not TRULENS_AVAILABLE:
            print("[TruLens] trulens-providers-bedrock not installed. "
                  "Run: pip install trulens-providers-bedrock", file=sys.stderr)
        else:
            trulens_m = score_trulens_rag_triad(succeeded)

    # ── Build and save report ─────────────────────────────────────────────────
    elapsed = time.monotonic() - t0
    report  = build_report(emails, succeeded, cases, intent_m, routing_m, entity_m,
                           rag_m, crm_m, response_m, calib_m, elapsed, run_id,
                           biobert_m=biobert_m, trulens_m=trulens_m)

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Report saved: {args.output}")

    # ── Upload to S3 ─────────────────────────────────────────────────────────
    payload = json.dumps(report, indent=2).encode()
    for key in (f"assessment/stepfn_{run_id}.json", "assessment/latest.json"):
        s3_client.put_object(Bucket=LOGS_BUCKET, Key=key, Body=payload,
                             ContentType="application/json")
        print(f"Uploaded s3://{LOGS_BUCKET}/{key}")

    # ── Print summary ─────────────────────────────────────────────────────────
    print_report(report)

    return 0 if report["assessment_metadata"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
