#!/usr/bin/env python3
"""
run_entity_eval.py
==================
Standalone task-based evaluation for entity extraction across all 14 document
categories in attachment_content.jsonl.

Uses Bedrock Claude 3 Haiku with a dynamic, category-aware extraction prompt
that asks for exactly the fields present in structured_gold_fields.

Usage
-----
    python scripts/run_entity_eval.py [--sample 5]

  --sample  Max records per doc_category (default: 5 → up to 70 total)

Output
------
  results/entity_eval_<timestamp>.json
  s3://insuremail-ai-dev-logs/eval_reports/entity_eval_latest.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3

ROOT        = Path(__file__).resolve().parent.parent
LOGS_BUCKET = os.environ.get("RESULTS_BUCKET", "insuremail-ai-dev-logs")
REGION      = os.environ.get("AWS_REGION", "us-east-1")
RESULTS_DIR = ROOT / "results"
DEFAULT_DATASET = ROOT / "tests/test_data/laya_synthetic_dataset_starter/attachment_content.jsonl"

# Mistral 7B — available locally for structured extraction
EXTRACTION_MODEL_ID = "mistral.mistral-7b-instruct-v0:2"

bedrock   = boto3.client("bedrock-runtime", region_name=REGION)
s3_client = boto3.client("s3",             region_name=REGION)


# ── Dynamic Bedrock extraction ────────────────────────────────────────────────

def _build_extraction_prompt(doc_category: str, raw_text: str, field_names: List[str]) -> str:
    fields_spec = "\n".join(f'  "{f}": <value or null>' for f in field_names)
    return (
        f"You are an insurance document entity extractor.\n"
        f"Document type: {doc_category.upper()}\n\n"
        f"Extract the following fields from the document text below. "
        f"Return ONLY valid JSON with exactly these keys. Use null for missing fields.\n\n"
        f"Fields to extract:\n{fields_spec}\n\n"
        f"Document text:\n\"\"\"\n{raw_text[:6000]}\n\"\"\"\n\n"
        f"Respond ONLY with a JSON object. No explanation, no markdown."
    )


def _extract_via_claude(
    doc_category: str,
    raw_text: str,
    field_names: List[str],
) -> Tuple[Dict[str, Any], float]:
    """Call Claude 3 Haiku to extract structured fields. Returns (fields, confidence)."""
    prompt = _build_extraction_prompt(doc_category, raw_text, field_names)
    try:
        resp = bedrock.invoke_model(
            modelId=EXTRACTION_MODEL_ID,
            body=json.dumps({
                "prompt":      f"<s>[INST] {prompt} [/INST]",
                "max_tokens":  1024,
                "temperature": 0.0,
            }),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(resp["body"].read())
        text_out = raw["outputs"][0]["text"]
    except Exception as exc:
        return {}, 0.5

    # Parse JSON from output
    match = re.search(r"\{[\s\S]*\}", text_out)
    if not match:
        return {}, 0.4

    try:
        extracted = json.loads(match.group())
        confidence = 0.85
        return extracted, confidence
    except Exception:
        return {}, 0.4


# ── String normalisation ──────────────────────────────────────────────────────

def normalize_str(value: Any) -> str:
    if value is None:
        return ""
    s = re.sub(r"\s+", " ", str(value).strip().lower())
    s = s.replace("'", "").replace("-", " ")
    return s


def exact_match(gold: Any, pred: Any) -> bool:
    return normalize_str(gold) == normalize_str(pred)


def partial_match(gold: Any, pred: Any) -> bool:
    g, p = normalize_str(gold), normalize_str(pred)
    if not g or not p:
        return False
    return g in p or p in g


# ── Dataset ────────────────────────────────────────────────────────────────────

def load_dataset(path: Path, max_per_category: int) -> List[Dict]:
    """Load up to max_per_category records per doc_category."""
    by_cat: Dict[str, List[Dict]] = defaultdict(list)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            cat = rec.get("doc_category", "unknown")
            if len(by_cat[cat]) < max_per_category:
                by_cat[cat].append(rec)

    records = [r for recs in by_cat.values() for r in recs]
    return records


# ── Evaluation ─────────────────────────────────────────────────────────────────

def evaluate_record(record: Dict) -> Dict:
    doc_category = record.get("doc_category", "unknown")
    raw_text     = record.get("raw_text", "")
    gold_fields  = record.get("structured_gold_fields", {})
    rec_id       = record.get("raw_text_id", record.get("attachment_id", ""))

    field_names = list(gold_fields.keys())

    t0 = time.monotonic()
    extracted: Dict[str, Any] = {}
    confidence: float = 0.5
    error: Optional[str] = None

    try:
        extracted, confidence = _extract_via_claude(doc_category, raw_text, field_names)
    except Exception as exc:
        error = str(exc)[:200]

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Score each gold field
    field_scores: Dict[str, Dict] = {}
    for field_name, gold_val in gold_fields.items():
        pred_val = extracted.get(field_name)

        # Normalise "NOT COMPLETED" placeholder
        if isinstance(pred_val, str) and "not completed" in pred_val.lower():
            pred_val = None

        gold_present = gold_val is not None
        pred_present = pred_val is not None

        if gold_present:
            if pred_present:
                is_exact   = exact_match(gold_val, pred_val)
                is_partial = is_exact or partial_match(gold_val, pred_val)
                outcome = "tp_exact" if is_exact else ("tp_partial" if is_partial else "fn")
            else:
                outcome = "fn"
        else:
            outcome = "fp" if pred_present else "tn"

        field_scores[field_name] = {
            "gold_present": gold_present,
            "pred_present": pred_present,
            "outcome":      outcome,
        }

    return {
        "record_id":    rec_id,
        "doc_category": doc_category,
        "latency_ms":   latency_ms,
        "confidence":   confidence,
        "error":        error,
        "field_scores": field_scores,
    }


# ── Aggregation ────────────────────────────────────────────────────────────────

def aggregate(results: List[Dict]) -> Dict:
    field_stats: Dict[str, Dict] = defaultdict(lambda: {
        "tp_exact": 0, "tp_partial": 0, "fp": 0, "fn": 0, "tn": 0,
        "gold_present": 0,
    })
    cat_field_f1s: Dict[str, List[float]] = defaultdict(list)

    for rec in results:
        for fname, fs in (rec.get("field_scores") or {}).items():
            st = field_stats[fname]
            out = fs["outcome"]
            if fs["gold_present"]:
                st["gold_present"] += 1
                if out == "tp_exact":
                    st["tp_exact"] += 1
                    st["tp_partial"] += 1
                elif out == "tp_partial":
                    st["tp_partial"] += 1
                    st["fn"] += 1
                else:
                    st["fn"] += 1
            else:
                if out == "fp":
                    st["fp"] += 1
                else:
                    st["tn"] += 1

    def _f1(tp, fp, fn):
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        return round(2 * p * r / (p + r), 4) if (p + r) else 0.0

    per_field: Dict[str, Dict] = {}
    for fname, st in field_stats.items():
        tp_e, fp, fn = st["tp_exact"], st["fp"], st["fn"]
        tp_p = st["tp_partial"]
        per_field[fname] = {
            "gold_present":     st["gold_present"],
            "precision_exact":  round(tp_e / (tp_e + fp), 4) if (tp_e + fp) else 0.0,
            "recall_exact":     round(tp_e / (tp_e + fn), 4) if (tp_e + fn) else 0.0,
            "f1_exact":         _f1(tp_e, fp, fn),
            "f1_partial":       _f1(tp_p, fp, fn),
        }

    for rec in results:
        cat = rec["doc_category"]
        for fname, fs in (rec.get("field_scores") or {}).items():
            if fs["gold_present"] and fname in per_field:
                cat_field_f1s[cat].append(per_field[fname]["f1_partial"])

    per_category = {
        cat: round(sum(f1s) / len(f1s), 4) if f1s else 0.0
        for cat, f1s in cat_field_f1s.items()
    }

    all_f1s = [v["f1_partial"] for v in per_field.values() if v["gold_present"] > 0]
    overall_score = round(sum(all_f1s) / len(all_f1s), 4) if all_f1s else 0.0

    return {
        "overall_score": overall_score,
        "per_field":     per_field,
        "per_category":  per_category,
    }


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_report(run_summary: Dict, agg: Dict) -> None:
    SEP = "=" * 68
    print(f"\n{SEP}")
    print("  Entity Extraction Evaluation — InsureMail AI")
    print(SEP)
    print(f"  Records   : {run_summary['n_records']}  |  Succeeded: {run_summary['n_succeeded']}  |  Failed: {run_summary['n_failed']}")
    print(f"  Avg latency: {run_summary['avg_latency_ms']:.0f} ms  |  Model: Mistral 7B")

    status = "PASSED" if agg["overall_score"] >= 0.70 else "FAILED"
    print(f"\n  Overall Score: {agg['overall_score']:.4f}  [{status}]  (threshold=0.70)")

    print(f"\n  Per-Category avg F1:")
    for cat, f1 in sorted(agg["per_category"].items()):
        bar = "█" * int(f1 * 20)
        print(f"    {cat:<30}  {f1:.3f}  {bar}")

    print(f"\n  {'Field':<35}  {'GP':>5}  {'Prec':>7}  {'Rec':>6}  {'F1(E)':>6}  {'F1(P)':>6}")
    print(f"  {'-'*66}")
    for fname, s in sorted(agg["per_field"].items(), key=lambda x: -x[1]["gold_present"]):
        if s["gold_present"] == 0:
            continue
        print(f"  {fname:<35}  {s['gold_present']:>5}  "
              f"{s['precision_exact']:>7.3f}  {s['recall_exact']:>6.3f}  "
              f"{s['f1_exact']:>6.3f}  {s['f1_partial']:>6.3f}")
    print(SEP)


def upload_to_s3(local_path: str) -> None:
    try:
        with open(local_path, "rb") as fh:
            s3_client.put_object(
                Bucket=LOGS_BUCKET,
                Key="eval_reports/entity_eval_latest.json",
                Body=fh.read(),
                ContentType="application/json",
            )
        print(f"Uploaded to s3://{LOGS_BUCKET}/eval_reports/entity_eval_latest.json")
    except Exception as e:
        print(f"[warn] S3 upload skipped: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Entity extraction task-based evaluation.")
    p.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p.add_argument("--sample",  type=int, default=5, help="Max records per doc_category")
    p.add_argument("--output",  default=None)
    return p.parse_args()


def main() -> None:
    args    = parse_args()
    records = load_dataset(Path(args.dataset), args.sample)
    print(f"Loaded {len(records)} records ({args.sample} per category) from {args.dataset}")
    print(f"Extracting with Mistral 7B (dynamic field-aware prompt)...\n")

    results: List[Dict] = []
    for i, rec in enumerate(records, 1):
        print(f"  [{i:>3}/{len(records)}] {rec.get('raw_text_id',''):<20}  cat={rec.get('doc_category',''):<25}", end="", flush=True)
        row = evaluate_record(rec)
        results.append(row)
        status = "ERR" if row["error"] else "OK "
        print(f"  {status}  conf={row['confidence']:.3f}  {row['latency_ms']}ms")

    n_succeeded = sum(1 for r in results if not r["error"])
    avg_latency = sum(r["latency_ms"] for r in results) / len(results) if results else 0.0

    run_summary = {
        "n_records":     len(results),
        "n_succeeded":   n_succeeded,
        "n_failed":      len(results) - n_succeeded,
        "avg_latency_ms": round(avg_latency, 1),
        "avg_confidence": round(sum(r["confidence"] for r in results if not r["error"]) / max(n_succeeded, 1), 3),
        "model":         EXTRACTION_MODEL_ID,
    }

    agg = aggregate(results)
    print_report(run_summary, agg)

    report = {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_path":  args.dataset,
        "run_summary":   run_summary,
        "overall_score": agg["overall_score"],
        "per_field":     agg["per_field"],
        "per_category":  agg["per_category"],
        "record_details": [
            {k: v for k, v in r.items() if k != "field_scores"}
            for r in results
        ],
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.output or str(RESULTS_DIR / f"entity_eval_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"\nResults written to: {out_path}")

    upload_to_s3(out_path)


if __name__ == "__main__":
    main()
