#!/usr/bin/env python3
"""
run_intent_eval.py
==================
Standalone task-based evaluation for the Intent Classification module.

Invokes the classify_intent_by_llm Lambda directly for each email in the
Laya dataset and scores predictions against gold labels.

Usage
-----
    python scripts/run_intent_eval.py [--sample 50] [--output PATH]

Options
-------
  --sample   Number of emails to evaluate (default: 50; 0 = all)
  --output   Path for JSON output (default: results/intent_eval_<ts>.json)

Output
------
  results/intent_eval_<timestamp>.json  (local)
  s3://insuremail-ai-dev-logs/eval_reports/intent_eval_latest.json  (S3)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parent.parent
RESULTS_DIR  = ROOT / "results"
DEFAULT_EMAILS = ROOT / "tests/test_data/laya_synthetic_dataset_starter/emails.jsonl"

# ── AWS config ─────────────────────────────────────────────────────────────────
REGION         = os.environ.get("AWS_REGION", "us-east-1")
LOGS_BUCKET    = os.environ.get("RESULTS_BUCKET", "insuremail-ai-dev-logs")
LAMBDA_NAME    = os.environ.get("INTENT_LAMBDA", "insuremail-ai-dev-classify-intent-by-llm")
CONCURRENCY    = 5

INTENT_TO_ROUTE = {
    "coverage_query":            "customer_support_team",
    "claim_submission":          "claims_team",
    "claim_status":              "claims_team",
    "claim_reimbursement_query": "claims_team",
    "pre_authorisation":         "medical_review_team",
    "payment_issue":             "finance_support_team",
    "policy_change":             "policy_admin_team",
    "renewal_query":             "renewals_team",
    "cancellation_request":      "retention_team",
    "enrollment_new_policy":     "sales_enrollment_team",
    "dependent_addition":        "policy_admin_team",
    "complaint":                 "complaints_team",
    "document_followup":         "operations_team",
    "hospital_network_query":    "provider_support_team",
    "id_verification":           "operations_team",
    "broker_query":              "general_support_team",
    "other":                     "general_support_team",
}

lambda_client = boto3.client("lambda", region_name=REGION)
s3_client     = boto3.client("s3",     region_name=REGION)


# ── Dataset ────────────────────────────────────────────────────────────────────

def load_emails(path: Path, sample: int) -> List[Dict]:
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    if sample and sample > 0:
        records = records[:sample]
    return records


# ── Lambda invocation ──────────────────────────────────────────────────────────

def invoke_intent_lambda(record: Dict) -> Dict:
    email_id  = record.get("email_id", "")
    body_text = record.get("body_text", record.get("body", ""))
    subject   = record.get("subject", "")

    payload = json.dumps({
        "email_id":   email_id,
        "email_body": body_text,
        "subject":    subject,
    }).encode()

    t0 = time.monotonic()
    try:
        raw = lambda_client.invoke(
            FunctionName=LAMBDA_NAME,
            InvocationType="RequestResponse",
            Payload=payload,
        )
        body = json.loads(raw["Payload"].read())
        latency_ms = int((time.monotonic() - t0) * 1000)

        # Lambda may return body as JSON string (API Gateway proxy format)
        if isinstance(body.get("body"), str):
            body = json.loads(body["body"])

        classification = body.get("classification", {})
        predicted_intent = classification.get("customer_intent", "other")
        # Always derive routing from our canonical INTENT_TO_ROUTE map so that
        # routing accuracy == intent accuracy (routing is a deterministic mapping).
        predicted_route = INTENT_TO_ROUTE.get(predicted_intent, "general_support_team")

        gold_intent = record.get("customer_intent", "")
        gold_route  = INTENT_TO_ROUTE.get(gold_intent, "general_support_team")

        return {
            "email_id":        email_id,
            "gold_intent":     gold_intent,
            "gold_route":      gold_route,
            "predicted_intent": predicted_intent,
            "predicted_route":  predicted_route,
            "latency_ms":      latency_ms,
            "error":           None,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        gold_intent = record.get("customer_intent", "")
        return {
            "email_id":        email_id,
            "gold_intent":     gold_intent,
            "gold_route":      INTENT_TO_ROUTE.get(gold_intent, "general_support_team"),
            "predicted_intent": "other",
            "predicted_route":  "general_support_team",
            "latency_ms":      latency_ms,
            "error":           str(exc)[:200],
        }


# ── Scoring ────────────────────────────────────────────────────────────────────

def score_intent(results: List[Dict]) -> Dict:
    correct = sum(1 for r in results if r["predicted_intent"] == r["gold_intent"] and not r["error"])
    total   = len(results)
    accuracy = correct / total if total else 0.0

    per_class: Dict[str, Dict] = {}
    for r in results:
        if r["error"]:
            continue
        g, p = r["gold_intent"], r["predicted_intent"]
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
    for intent, c in per_class.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec  = tp / (tp + fn) if (tp + fn) else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class_scores[intent] = {
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4), "support": c["support"],
        }

    f1s = [v["f1"] for v in per_class_scores.values()]
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0

    confused = Counter(
        (r["gold_intent"], r["predicted_intent"])
        for r in results if r["predicted_intent"] != r["gold_intent"] and not r["error"]
    )
    top_confused = [
        {"true": g, "predicted": p, "count": c}
        for (g, p), c in confused.most_common(5)
    ]

    return {
        "accuracy":    round(accuracy, 4),
        "macro_f1":    round(macro_f1, 4),
        "n_samples":   total,
        "n_correct":   correct,
        "per_class":   per_class_scores,
        "top_confused": top_confused,
    }


def score_routing(results: List[Dict]) -> Dict:
    valid = [r for r in results if not r["error"]]
    correct = sum(1 for r in valid if r["predicted_route"].lower() == r["gold_route"].lower())
    total   = len(valid)

    per_team: Dict[str, Dict] = {}
    for r in valid:
        t = r["gold_route"]
        per_team.setdefault(t, {"correct": 0, "total": 0})
        per_team[t]["total"] += 1
        if r["predicted_route"].lower() == t.lower():
            per_team[t]["correct"] += 1

    return {
        "routing_accuracy": round(correct / total, 4) if total else 0.0,
        "correct": correct,
        "total":   total,
        "per_team": {
            t: round(v["correct"] / v["total"], 4) if v["total"] else 0.0
            for t, v in per_team.items()
        },
    }


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_report(run_summary: Dict, intent_m: Dict, routing_m: Dict) -> None:
    SEP = "=" * 68
    print(f"\n{SEP}")
    print("  Intent Classification Evaluation — InsureMail AI")
    print(SEP)
    print(f"  Records   : {run_summary['n_emails']}  |  Succeeded: {run_summary['n_succeeded']}  |  Failed: {run_summary['n_failed']}")
    print(f"  Avg latency: {run_summary['avg_latency_ms']:.0f} ms")

    status = "PASSED" if intent_m["accuracy"] >= 0.80 else "FAILED"
    print(f"\n  Intent Accuracy : {intent_m['accuracy']:.4f}  [{status}]  (threshold=0.80)")
    print(f"  Macro F1        : {intent_m['macro_f1']:.4f}")
    print(f"  Routing Accuracy: {routing_m['routing_accuracy']:.4f}")

    print(f"\n  {'-'*64}")
    print(f"  {'Intent':<35}  {'Supp':>5}  {'Prec':>7}  {'Rec':>7}  {'F1':>7}")
    print(f"  {'-'*64}")
    for intent, s in sorted(intent_m["per_class"].items()):
        print(f"  {intent:<35}  {s['support']:>5}  {s['precision']:>7.3f}  {s['recall']:>7.3f}  {s['f1']:>7.3f}")

    if intent_m["top_confused"]:
        print(f"\n  Top confused pairs:")
        for p in intent_m["top_confused"]:
            print(f"    {p['true']:<30} → {p['predicted']:<30} (n={p['count']})")

    print(f"\n  Routing per team:")
    for team, acc in sorted(routing_m["per_team"].items()):
        bar = "█" * int(acc * 20)
        print(f"    {team:<30} {acc:.3f}  {bar}")
    print(SEP)


# ── S3 upload ─────────────────────────────────────────────────────────────────

def upload_to_s3(local_path: str) -> None:
    try:
        with open(local_path, "rb") as fh:
            s3_client.put_object(
                Bucket=LOGS_BUCKET,
                Key="eval_reports/intent_eval_latest.json",
                Body=fh.read(),
                ContentType="application/json",
            )
        print(f"Uploaded to s3://{LOGS_BUCKET}/eval_reports/intent_eval_latest.json")
    except Exception as e:
        print(f"[warn] S3 upload skipped: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Intent classification task-based evaluation.")
    p.add_argument("--emails",  default=str(DEFAULT_EMAILS))
    p.add_argument("--sample",  type=int, default=50)
    p.add_argument("--output",  default=None)
    p.add_argument("--concurrency", type=int, default=CONCURRENCY)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    records = load_emails(Path(args.emails), args.sample)
    print(f"Loaded {len(records)} emails from {args.emails}")
    print(f"Invoking {LAMBDA_NAME} with concurrency={args.concurrency}...\n")

    results: List[Dict] = []
    n_done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(invoke_intent_lambda, r): r for r in records}
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            n_done += 1
            status = "ERR" if row["error"] else "OK "
            print(f"  [{n_done:>3}/{len(records)}] {row['email_id']:<20}  {status}  "
                  f"gold={row['gold_intent']:<30}  pred={row['predicted_intent']:<30}  "
                  f"{row['latency_ms']}ms")

    n_succeeded = sum(1 for r in results if not r["error"])
    n_failed    = len(results) - n_succeeded
    avg_latency = sum(r["latency_ms"] for r in results) / len(results) if results else 0.0

    run_summary = {
        "n_emails":     len(results),
        "n_succeeded":  n_succeeded,
        "n_failed":     n_failed,
        "avg_latency_ms": round(avg_latency, 1),
    }

    intent_m  = score_intent(results)
    routing_m = score_routing(results)

    print_report(run_summary, intent_m, routing_m)

    report = {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_path":   args.emails,
        "lambda_name":    LAMBDA_NAME,
        "run_summary":    run_summary,
        "intent_classification": intent_m,
        "routing":        routing_m,
        "per_email_results": [
            {k: v for k, v in r.items()} for r in results
        ],
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.output or str(RESULTS_DIR / f"intent_eval_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"\nResults written to: {out_path}")

    upload_to_s3(out_path)


if __name__ == "__main__":
    main()
