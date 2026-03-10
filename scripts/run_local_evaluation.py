#!/usr/bin/env python3
"""
Local evaluation runner for InsureMail AI.

Measures 3 metric dimensions locally via Bedrock Haiku:
  1. Intent classification + routing + confidence calibration
  2. Entity extraction accuracy
  3. (RAG response quality is read from existing Bedrock eval job results)

CLI usage:
  python scripts/run_local_evaluation.py [--n-emails N] [--n-attachments N] [--dry-run]

Results are saved to results/eval_report_<timestamp>.json.
"""
import argparse
import json
import os
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
LAYA_DIR  = REPO_ROOT / "tests" / "test_data" / "laya_synthetic_dataset_starter"
RESULTS_DIR = REPO_ROOT / "results"
RAG_EVAL_JSONL = REPO_ROOT / "lambda" / "bedrock_evaluation" / "laya_rag_eval.jsonl"

JUDGE_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"

# 17 laya intents
VALID_INTENTS = {
    'coverage_query', 'claim_submission', 'claim_status',
    'claim_reimbursement_query', 'pre_authorisation', 'payment_issue',
    'policy_change', 'renewal_query', 'cancellation_request',
    'enrollment_new_policy', 'dependent_addition', 'complaint',
    'document_followup', 'hospital_network_query', 'id_verification',
    'broker_query', 'other',
}

INTENT_TO_ROUTE = {
    'coverage_query':            'customer_support_team',
    'claim_submission':          'claims_team',
    'claim_status':              'claims_team',
    'claim_reimbursement_query': 'claims_team',
    'pre_authorisation':         'medical_review_team',
    'payment_issue':             'finance_support_team',
    'policy_change':             'policy_admin_team',
    'renewal_query':             'renewals_team',
    'cancellation_request':      'retention_team',
    'enrollment_new_policy':     'sales_enrollment_team',
    'dependent_addition':        'policy_admin_team',
    'complaint':                 'complaints_team',
    'document_followup':         'operations_team',
    'hospital_network_query':    'provider_support_team',
    'id_verification':           'operations_team',
    'broker_query':              'general_support_team',
    'other':                     'general_support_team',
}

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> List[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def stratified_sample(records: List[dict], key: str, n: int, seed: int = 42) -> List[dict]:
    rng = random.Random(seed)
    by_stratum: Dict[str, List[dict]] = defaultdict(list)
    for r in records:
        by_stratum[r.get(key, "unknown")].append(r)
    strata = list(by_stratum.keys())
    per_stratum = max(1, n // len(strata))
    sampled: List[dict] = []
    for items in by_stratum.values():
        rng.shuffle(items)
        sampled.extend(items[:per_stratum])
    rng.shuffle(sampled)
    if len(sampled) < n:
        remaining = [r for r in records if r not in sampled]
        rng.shuffle(remaining)
        sampled.extend(remaining[: n - len(sampled)])
    return sampled[:n]


# ---------------------------------------------------------------------------
# Bedrock helpers
# ---------------------------------------------------------------------------

def bedrock_client():
    import boto3
    return boto3.client("bedrock-runtime")


def invoke_haiku(client, prompt: str) -> str:
    """Call Bedrock Haiku and return the text response."""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "temperature": 0.0,
        "messages": [{"role": "user", "content": prompt}],
    })
    resp = client.invoke_model(
        modelId=JUDGE_MODEL,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    data = json.loads(resp["body"].read())
    return data.get("content", [{}])[0].get("text", "")


# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

CLASSIFICATION_PROMPT = """\
You are an AI assistant for a health insurance company.
Classify the following customer email into exactly one of these 17 intent categories:

coverage_query, claim_submission, claim_status, claim_reimbursement_query,
pre_authorisation, payment_issue, policy_change, renewal_query,
cancellation_request, enrollment_new_policy, dependent_addition, complaint,
document_followup, hospital_network_query, id_verification, broker_query, other

EMAIL:
{body_text}

Respond ONLY with a JSON object — no other text:
{{"intent": "<one of the 17 categories>", "confidence": <0.0-1.0>, "route_team": "<team>"}}"""


def parse_classification(raw: str) -> Tuple[str, float, str]:
    """Return (intent, confidence, route_team) from model JSON output."""
    text = raw.strip()
    for fence in ("```json", "```"):
        if fence in text:
            text = text.split(fence)[1].split("```")[0].strip()
            break
    try:
        parsed = json.loads(text)
        intent = parsed.get("intent", "").strip().lower()
        if intent not in VALID_INTENTS:
            intent = "other"
        confidence = float(parsed.get("confidence", 0.5))
        route_team = parsed.get("route_team") or INTENT_TO_ROUTE.get(intent, "general_support_team")
        return intent, confidence, route_team
    except (json.JSONDecodeError, ValueError, TypeError):
        # Fallback: search for any valid intent in the raw text
        lower = text.lower()
        for cat in VALID_INTENTS:
            if cat in lower:
                return cat, 0.4, INTENT_TO_ROUTE.get(cat, "general_support_team")
        return "other", 0.2, "general_support_team"


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def compute_f1_metrics(
    y_true: List[str], y_pred: List[str], labels: List[str]
) -> Dict[str, Any]:
    """Compute per-class and macro/weighted F1."""
    counts: Dict[str, Dict[str, int]] = {
        lab: {"tp": 0, "fp": 0, "fn": 0} for lab in labels
    }
    for true, pred in zip(y_true, y_pred):
        for lab in labels:
            if true == lab and pred == lab:
                counts[lab]["tp"] += 1
            elif true != lab and pred == lab:
                counts[lab]["fp"] += 1
            elif true == lab and pred != lab:
                counts[lab]["fn"] += 1

    per_class = {}
    macro_p, macro_r, macro_f1 = [], [], []
    support: Dict[str, int] = defaultdict(int)
    for t in y_true:
        support[t] += 1

    for lab in labels:
        tp = counts[lab]["tp"]
        fp = counts[lab]["fp"]
        fn = counts[lab]["fn"]
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        per_class[lab] = {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}
        macro_p.append(p)
        macro_r.append(r)
        macro_f1.append(f1)

    n = len(y_true)
    weighted_f1 = sum(
        per_class[lab]["f1"] * support.get(lab, 0) / n
        for lab in labels
    ) if n > 0 else 0.0

    return {
        "per_class": per_class,
        "macro_precision": round(sum(macro_p) / len(macro_p), 4) if macro_p else 0,
        "macro_recall":    round(sum(macro_r) / len(macro_r), 4) if macro_r else 0,
        "macro_f1":        round(sum(macro_f1) / len(macro_f1), 4) if macro_f1 else 0,
        "weighted_f1":     round(weighted_f1, 4),
    }


# ---------------------------------------------------------------------------
# Dimension 1 — Intent + Routing + Confidence
# ---------------------------------------------------------------------------

def evaluate_intent_routing(
    client,
    emails: List[dict],
    cases: List[dict],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Sample N emails, call Haiku with classification prompt, compare against gold labels.
    """
    print(f"\n[1/3] Intent classification + routing + calibration ({len(emails)} emails)")

    case_by_email = {c["email_id"]: c for c in cases}

    y_true_intent, y_pred_intent = [], []
    y_true_route,  y_pred_route  = [], []
    missed_escalations, false_escalations = 0, 0
    auto_respond_total, auto_respond_true = 0, 0
    raw_results = []

    for i, email in enumerate(emails, 1):
        eid = email["email_id"]
        gold_intent = email.get("customer_intent", "other")
        gold_route  = email.get("gold_route_team", "")
        requires_review = email.get("requires_human_review", False)

        if dry_run:
            pred_intent = gold_intent  # perfect mock
            confidence  = 0.85
            pred_route  = INTENT_TO_ROUTE.get(gold_intent, "general_support_team")
        else:
            prompt = CLASSIFICATION_PROMPT.format(body_text=email.get("body_text", ""))
            try:
                raw = invoke_haiku(client, prompt)
                pred_intent, confidence, pred_route = parse_classification(raw)
            except Exception as exc:
                print(f"  [WARN] email {eid}: {exc}")
                pred_intent, confidence, pred_route = "other", 0.2, "general_support_team"

        # Confidence-based action
        if confidence >= 0.8:
            action = "auto_response"
        elif confidence >= 0.5:
            action = "human_review"
        else:
            action = "escalate"

        # Calibration
        if action == "auto_response":
            auto_respond_total += 1
            if not requires_review:
                auto_respond_true += 1
            if requires_review:
                missed_escalations += 1
        elif action == "escalate" and not requires_review:
            false_escalations += 1

        y_true_intent.append(gold_intent)
        y_pred_intent.append(pred_intent)
        y_true_route.append(gold_route)
        y_pred_route.append(pred_route)

        raw_results.append({
            "email_id":       eid,
            "gold_intent":    gold_intent,
            "pred_intent":    pred_intent,
            "gold_route":     gold_route,
            "pred_route":     pred_route,
            "confidence":     confidence,
            "action":         action,
            "requires_review": requires_review,
        })

        if i % 10 == 0:
            print(f"  Processed {i}/{len(emails)} emails")

    n = len(emails)
    intent_accuracy  = sum(t == p for t, p in zip(y_true_intent, y_pred_intent)) / n if n else 0
    routing_accuracy = sum(t == p for t, p in zip(y_true_route, y_pred_route)) / n if n else 0

    # Calibration rates
    auto_n  = auto_respond_total
    others_n = n - auto_respond_total
    missed_rate = missed_escalations / auto_n if auto_n > 0 else 0.0
    false_rate  = false_escalations / others_n if others_n > 0 else 0.0
    prec_at_08  = auto_respond_true / auto_respond_total if auto_respond_total > 0 else 0.0
    recall_at_08 = auto_respond_total / n if n > 0 else 0.0

    intent_labels = sorted(VALID_INTENTS)
    intent_f1 = compute_f1_metrics(y_true_intent, y_pred_intent, intent_labels)

    route_labels = sorted(set(y_true_route + y_pred_route))
    route_f1 = compute_f1_metrics(y_true_route, y_pred_route, route_labels)

    # Critical misroute: routed to general_support_team when gold is specialist
    specialist_teams = {
        "claims_team", "medical_review_team", "finance_support_team",
        "policy_admin_team", "renewals_team", "retention_team",
        "sales_enrollment_team", "complaints_team", "operations_team",
        "provider_support_team", "customer_support_team",
    }
    critical_misroutes = sum(
        1 for t, p in zip(y_true_route, y_pred_route)
        if t in specialist_teams and p == "general_support_team"
    )
    critical_misroute_rate = critical_misroutes / n if n else 0.0

    return {
        "n": n,
        "intent_accuracy":        round(intent_accuracy, 4),
        "routing_accuracy":       round(routing_accuracy, 4),
        "intent_macro_f1":        intent_f1["macro_f1"],
        "intent_weighted_f1":     intent_f1["weighted_f1"],
        "intent_per_class_f1":    intent_f1["per_class"],
        "routing_macro_f1":       route_f1["macro_f1"],
        "routing_per_team_f1":    route_f1["per_class"],
        "critical_misroute_rate": round(critical_misroute_rate, 4),
        "missed_escalation_rate": round(missed_rate, 4),
        "false_escalation_rate":  round(false_rate, 4),
        "threshold_precision_08": round(prec_at_08, 4),
        "threshold_recall_08":    round(recall_at_08, 4),
        "raw": raw_results,
    }


# ---------------------------------------------------------------------------
# Dimension 2 — Entity Extraction
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
You are an information extraction assistant. Extract structured fields from the following document text.
Output ONLY a JSON object with the field values found in the text. Use null for missing fields.

Document category: {doc_category}
Document text: {raw_text}

Return JSON only:"""


def evaluate_entity_extraction(
    client,
    attachment_content: List[dict],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Sample N attachment records, extract fields with Haiku, compare against structured_gold_fields.
    """
    print(f"\n[2/3] Entity extraction ({len(attachment_content)} records)")

    by_category: Dict[str, int] = defaultdict(int)
    by_category_correct: Dict[str, int] = defaultdict(int)
    field_total: Dict[str, int] = defaultdict(int)
    field_correct: Dict[str, int] = defaultdict(int)
    record_correct = 0
    raw_results = []

    for i, record in enumerate(attachment_content, 1):
        doc_cat = record.get("doc_category", "unknown")
        raw_text = record.get("raw_text", "")
        gold = record.get("structured_gold_fields", {})

        if not gold:
            continue

        if dry_run:
            extracted = gold  # perfect mock
        else:
            prompt = EXTRACTION_PROMPT.format(doc_category=doc_cat, raw_text=raw_text)
            try:
                raw = invoke_haiku(client, prompt)
                text = raw.strip()
                for fence in ("```json", "```"):
                    if fence in text:
                        text = text.split(fence)[1].split("```")[0].strip()
                        break
                extracted = json.loads(text)
            except Exception as exc:
                print(f"  [WARN] record {i}: {exc}")
                extracted = {}

        # Field-level exact match
        all_match = True
        for field, gold_val in gold.items():
            pred_val = extracted.get(field)
            field_total[field] += 1
            by_category[doc_cat] += 1
            if str(pred_val).strip().lower() == str(gold_val).strip().lower():
                field_correct[field] += 1
                by_category_correct[doc_cat] += 1
            else:
                all_match = False

        if all_match:
            record_correct += 1

        raw_results.append({
            "doc_category": doc_cat,
            "gold": gold,
            "extracted": extracted,
            "all_match": all_match,
        })

        if i % 10 == 0:
            print(f"  Processed {i}/{len(attachment_content)} records")

    n = len([r for r in raw_results])
    total_fields = sum(field_total.values())

    field_accuracy = {
        f: round(field_correct[f] / field_total[f], 4)
        for f in field_total
        if field_total[f] > 0
    }
    per_category = {
        cat: round(by_category_correct[cat] / by_category[cat], 4)
        for cat in by_category
        if by_category[cat] > 0
    }

    return {
        "n": n,
        "record_accuracy":      round(record_correct / n, 4) if n else 0,
        "field_level_accuracy": round(sum(field_correct.values()) / total_fields, 4) if total_fields else 0,
        "per_field_accuracy":   field_accuracy,
        "per_category_accuracy": per_category,
        "raw": raw_results,
    }


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------

def print_summary(intent_result: Dict, extraction_result: Dict, rag_note: str) -> None:
    sep = "-" * 60

    print(f"\n{'=' * 60}")
    print("  InsureMail AI — Local Evaluation Summary")
    print(f"{'=' * 60}")

    print(f"\n{sep}")
    print("  DIMENSION 1: Intent Classification & Routing")
    print(sep)
    ir = intent_result
    print(f"  Emails evaluated:       {ir['n']}")
    print(f"  Intent accuracy:        {ir['intent_accuracy']:.2%}   (target ≥ 85%)")
    print(f"  Intent macro F1:        {ir['intent_macro_f1']:.4f}   (target ≥ 0.80)")
    print(f"  Intent weighted F1:     {ir['intent_weighted_f1']:.4f}  (target ≥ 0.85)")
    print(f"  Routing accuracy:       {ir['routing_accuracy']:.2%}   (target ≥ 88%)")
    print(f"  Routing macro F1:       {ir['routing_macro_f1']:.4f}")
    print(f"  Critical misroute rate: {ir['critical_misroute_rate']:.2%}   (target < 5%)")
    print(f"  Missed-escalation rate: {ir['missed_escalation_rate']:.2%}   (target < 2%)")
    print(f"  False-escalation rate:  {ir['false_escalation_rate']:.2%}   (target < 15%)")
    print(f"  Threshold precision@0.8:{ir['threshold_precision_08']:.4f}")
    print(f"  Threshold recall@0.8:   {ir['threshold_recall_08']:.4f}")

    print(f"\n{sep}")
    print("  DIMENSION 2: Entity Extraction")
    print(sep)
    er = extraction_result
    print(f"  Records evaluated:      {er['n']}")
    print(f"  Record-level accuracy:  {er['record_accuracy']:.2%}")
    print(f"  Field-level accuracy:   {er['field_level_accuracy']:.2%}")
    if er.get("per_category_accuracy"):
        print("  Per-category accuracy:")
        for cat, acc in sorted(er["per_category_accuracy"].items()):
            print(f"    {cat:<30} {acc:.2%}")

    print(f"\n{sep}")
    print("  DIMENSION 3: RAG Response Quality")
    print(sep)
    print(f"  {rag_note}")

    print(f"\n{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run local evaluation against laya dataset")
    parser.add_argument("--n-emails", type=int, default=50, help="Emails to evaluate (default 50)")
    parser.add_argument("--n-attachments", type=int, default=30, help="Attachments to evaluate (default 30)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true",
                        help="Use mock perfect predictions (no Bedrock calls)")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading laya dataset...")
    emails_all   = load_jsonl(LAYA_DIR / "emails.jsonl")
    cases_all    = load_jsonl(LAYA_DIR / "cases.jsonl")
    attach_all   = load_jsonl(LAYA_DIR / "attachment_content.jsonl")
    print(f"  emails={len(emails_all)}, cases={len(cases_all)}, attachment_content={len(attach_all)}")

    # Sample
    email_sample  = stratified_sample(emails_all, "customer_intent", args.n_emails, seed=args.seed)
    attach_sample = stratified_sample(attach_all, "doc_category", args.n_attachments, seed=args.seed + 10)

    client = None if args.dry_run else bedrock_client()

    # Dimension 1
    intent_result = evaluate_intent_routing(client, email_sample, cases_all, dry_run=args.dry_run)

    # Dimension 2
    extraction_result = evaluate_entity_extraction(client, attach_sample, dry_run=args.dry_run)

    # Dimension 3 — note only (Bedrock eval jobs run async)
    rag_note = (
        "RAG quality scored by Bedrock eval jobs (run bedrock_evaluation Lambda to collect)."
    )
    if RAG_EVAL_JSONL.exists():
        rag_note = f"RAG eval dataset ready: {RAG_EVAL_JSONL} ({RAG_EVAL_JSONL.stat().st_size // 1024} KB). "
        rag_note += "Submit via bedrock_evaluation Lambda (action=submit, dataset_source=laya)."

    print_summary(intent_result, extraction_result, rag_note)

    # Save report
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = RESULTS_DIR / f"eval_report_{ts}.json"
    report = {
        "generated_at":       ts,
        "dry_run":            args.dry_run,
        "n_emails":           args.n_emails,
        "n_attachments":      args.n_attachments,
        "intent_routing":     {k: v for k, v in intent_result.items() if k != "raw"},
        "entity_extraction":  {k: v for k, v in extraction_result.items() if k != "raw"},
        "rag_note":           rag_note,
        # Flat fields for DynamoDB write (used by evaluation_metrics Lambda)
        "intent_accuracy":              intent_result["intent_accuracy"],
        "routing_accuracy":             intent_result["routing_accuracy"],
        "missed_escalation_rate":       intent_result["missed_escalation_rate"],
        "false_escalation_rate":        intent_result["false_escalation_rate"],
        "extraction_record_accuracy":   extraction_result["record_accuracy"],
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Report saved → {report_path}")


if __name__ == "__main__":
    main()
