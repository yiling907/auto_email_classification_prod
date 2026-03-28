#!/usr/bin/env python3
"""
run_rag_eval.py
===============
Standalone task-based evaluation for the RAG Retrieval module.

Invokes the rag_retrieval Lambda directly for each email and scores
retrieval against gold grounded_doc_ids from draft_responses.jsonl.

Usage
-----
    python scripts/run_rag_eval.py [--sample 30]

Output
------
  results/rag_eval_<timestamp>.json
  s3://insuremail-ai-dev-logs/eval_reports/rag_eval_latest.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3

ROOT           = Path(__file__).resolve().parent.parent
RESULTS_DIR    = ROOT / "results"
DEFAULT_EMAILS = ROOT / "tests/test_data/laya_synthetic_dataset_starter/emails.jsonl"
DEFAULT_CASES  = ROOT / "tests/test_data/laya_synthetic_dataset_starter/cases.jsonl"
DEFAULT_DRAFTS = ROOT / "tests/test_data/laya_synthetic_dataset_starter/draft_responses.jsonl"

REGION      = os.environ.get("AWS_REGION", "us-east-1")
LOGS_BUCKET = os.environ.get("RESULTS_BUCKET", "insuremail-ai-dev-logs")
LAMBDA_NAME = os.environ.get("RAG_LAMBDA", "insuremail-ai-dev-rag-retrieval")
CONCURRENCY         = 5
SIMILARITY_THRESHOLD = 0.70   # minimum cosine similarity to count as a relevant hit

lambda_client = boto3.client("lambda", region_name=REGION)
s3_client     = boto3.client("s3",     region_name=REGION)


# ── Dataset loading ────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> List[Dict]:
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_gold_doc_map(cases: List[Dict], drafts: List[Dict]) -> Dict[str, List[str]]:
    """Map email_id → list of gold grounded_doc_ids."""
    draft_by_id = {d["draft_response_id"]: d for d in drafts}
    gold: Dict[str, List[str]] = {}
    for case in cases:
        email_id  = case.get("email_id", "")
        draft_id  = case.get("draft_response_id", "")
        draft     = draft_by_id.get(draft_id, {})
        doc_ids   = draft.get("grounded_doc_ids", [])
        if email_id and doc_ids:
            gold[email_id] = doc_ids
    return gold


# ── Lambda invocation ──────────────────────────────────────────────────────────

def invoke_rag_lambda(record: Dict, gold_doc_ids: List[str]) -> Dict:
    email_id  = record.get("email_id", "")
    body_text = record.get("body_text", record.get("body", ""))
    intent    = record.get("customer_intent", "")

    payload = json.dumps({
        "email_text": body_text,
        "intent":     intent,
        "top_k":      5,
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

        if isinstance(body.get("body"), str):
            body = json.loads(body["body"])

        docs         = body.get("retrieved_documents", [])
        retrieved_ids = [d.get("doc_id", "") for d in docs if d.get("doc_id")]
        num_docs      = len(docs)

        # Only count a doc as relevant if similarity_score >= SIMILARITY_THRESHOLD
        relevant_docs = [
            d for d in docs
            if (d.get("similarity_score") or 0.0) >= SIMILARITY_THRESHOLD
        ]
        relevant_ids  = [d.get("doc_id", "") for d in relevant_docs if d.get("doc_id")]
        num_relevant  = len(relevant_docs)

        # Doc precision: fraction of relevant retrieved IDs in gold set
        doc_precision = None
        if gold_doc_ids:
            gold_set = set(gold_doc_ids)
            hits = sum(1 for did in relevant_ids if did in gold_set)
            doc_precision = round(hits / num_relevant, 4) if num_relevant else 0.0

        return {
            "email_id":       email_id,
            "intent":         intent,
            "num_docs":       num_docs,
            "num_relevant":   num_relevant,
            "retrieved_ids":  retrieved_ids,
            "gold_doc_ids":   gold_doc_ids,
            "doc_precision":  doc_precision,
            "hit":            num_relevant > 0,   # hit only if ≥1 doc above threshold
            "latency_ms":     latency_ms,
            "error":          None,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {
            "email_id":      email_id,
            "intent":        intent,
            "num_docs":      0,
            "num_relevant":  0,
            "retrieved_ids": [],
            "gold_doc_ids":  gold_doc_ids,
            "doc_precision": None,
            "hit":           False,
            "latency_ms":    latency_ms,
            "error":         str(exc)[:200],
        }


# ── Scoring ────────────────────────────────────────────────────────────────────

def score_rag(results: List[Dict]) -> Dict:
    valid  = [r for r in results if not r["error"]]
    total  = len(results)
    hits   = sum(1 for r in valid if r["hit"])
    hit_rate = hits / total if total else 0.0
    avg_docs = sum(r["num_docs"] for r in valid) / len(valid) if valid else 0.0

    prec_vals = [r["doc_precision"] for r in valid if r["doc_precision"] is not None]
    avg_doc_precision = round(sum(prec_vals) / len(prec_vals), 4) if prec_vals else None

    # Per-intent hit rate
    by_intent: Dict[str, Dict] = defaultdict(lambda: {"hits": 0, "total": 0})
    for r in results:
        intent = r["intent"] or "unknown"
        by_intent[intent]["total"] += 1
        if r["hit"] and not r["error"]:
            by_intent[intent]["hits"] += 1
    per_intent = {
        k: round(v["hits"] / v["total"], 4) if v["total"] else 0.0
        for k, v in by_intent.items()
    }

    return {
        "hit_rate":           round(hit_rate, 4),
        "empty_retrieval_rate": round(1.0 - hit_rate, 4),
        "avg_docs_retrieved": round(avg_docs, 2),
        "avg_doc_precision":  avg_doc_precision,
        "hits":    hits,
        "total":   total,
        "per_intent": per_intent,
    }


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_report(run_summary: Dict, rag_m: Dict) -> None:
    SEP = "=" * 60
    print(f"\n{SEP}")
    print("  RAG Retrieval Evaluation — InsureMail AI")
    print(SEP)
    print(f"  Records : {run_summary['n_emails']}  |  Succeeded: {run_summary['n_succeeded']}  |  Failed: {run_summary['n_failed']}")
    print(f"  Avg latency: {run_summary['avg_latency_ms']:.0f} ms")

    status = "PASSED" if rag_m["hit_rate"] >= 0.60 else "FAILED"
    print(f"\n  Similarity Threshold: {SIMILARITY_THRESHOLD:.2f}")
    print(f"  Hit Rate            : {rag_m['hit_rate']:.4f}  [{status}]  (threshold=0.60)")
    print(f"  Empty Retrieval Rate: {rag_m['empty_retrieval_rate']:.4f}")
    print(f"  Avg Docs Retrieved  : {rag_m['avg_docs_retrieved']:.2f}")
    if rag_m["avg_doc_precision"] is not None:
        print(f"  Avg Doc Precision   : {rag_m['avg_doc_precision']:.4f}")

    print(f"\n  Per-Intent Hit Rate:")
    for intent, rate in sorted(rag_m["per_intent"].items()):
        bar = "█" * int(rate * 20)
        print(f"    {intent:<35}  {rate:.3f}  {bar}")
    print(SEP)


def upload_to_s3(local_path: str) -> None:
    try:
        with open(local_path, "rb") as fh:
            s3_client.put_object(
                Bucket=LOGS_BUCKET,
                Key="eval_reports/rag_eval_latest.json",
                Body=fh.read(),
                ContentType="application/json",
            )
        print(f"Uploaded to s3://{LOGS_BUCKET}/eval_reports/rag_eval_latest.json")
    except Exception as e:
        print(f"[warn] S3 upload skipped: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAG retrieval task-based evaluation.")
    p.add_argument("--emails",  default=str(DEFAULT_EMAILS))
    p.add_argument("--cases",   default=str(DEFAULT_CASES))
    p.add_argument("--drafts",  default=str(DEFAULT_DRAFTS))
    p.add_argument("--sample",  type=int, default=30)
    p.add_argument("--output",  default=None)
    p.add_argument("--concurrency", type=int, default=CONCURRENCY)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    emails = load_jsonl(Path(args.emails))
    if args.sample and args.sample > 0:
        emails = emails[:args.sample]

    cases  = load_jsonl(Path(args.cases))  if Path(args.cases).exists()  else []
    drafts = load_jsonl(Path(args.drafts)) if Path(args.drafts).exists() else []
    gold_map = build_gold_doc_map(cases, drafts)

    print(f"Loaded {len(emails)} emails, {len(gold_map)} with gold doc IDs")
    print(f"Invoking {LAMBDA_NAME} with concurrency={args.concurrency}...\n")

    results: List[Dict] = []
    n_done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(invoke_rag_lambda, r, gold_map.get(r.get("email_id", ""), [])): r
            for r in emails
        }
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            n_done += 1
            status = "ERR" if row["error"] else "OK "
            prec_str = f"  prec={row['doc_precision']:.3f}" if row["doc_precision"] is not None else ""
            print(f"  [{n_done:>3}/{len(emails)}] {row['email_id']:<20}  {status}  "
                  f"docs={row['num_docs']}(rel={row['num_relevant']})  "
                  f"hit={'Y' if row['hit'] else 'N'}{prec_str}  {row['latency_ms']}ms")

    n_succeeded = sum(1 for r in results if not r["error"])
    avg_latency = sum(r["latency_ms"] for r in results) / len(results) if results else 0.0

    run_summary = {
        "n_emails":      len(results),
        "n_succeeded":   n_succeeded,
        "n_failed":      len(results) - n_succeeded,
        "avg_latency_ms": round(avg_latency, 1),
    }

    rag_m = score_rag(results)
    print_report(run_summary, rag_m)

    report = {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_path":  args.emails,
        "lambda_name":   LAMBDA_NAME,
        "run_summary":   run_summary,
        "rag_retrieval": rag_m,
        "per_email_results": [
            {k: v for k, v in r.items() if k not in ("retrieved_ids", "gold_doc_ids")}
            for r in results
        ],
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.output or str(RESULTS_DIR / f"rag_eval_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"\nResults written to: {out_path}")

    upload_to_s3(out_path)


if __name__ == "__main__":
    main()
