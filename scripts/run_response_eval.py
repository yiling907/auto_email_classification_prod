#!/usr/bin/env python3
"""
run_response_eval.py
====================
Post-hoc response quality evaluation comparing pipeline-generated responses
against gold standard draft_responses.jsonl using token-overlap F1 (≈ ROUGE-L).

Loads the most recent stepfn_assessment JSON from results/ and joins
response_text against gold generated_reply via the cases join key.

Usage
-----
    python scripts/run_response_eval.py [--assessment PATH]

Output
------
  results/response_eval_<timestamp>.json
  s3://insuremail-ai-dev-logs/eval_reports/response_eval_latest.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import boto3

ROOT           = Path(__file__).resolve().parent.parent
RESULTS_DIR    = ROOT / "results"
DEFAULT_CASES  = ROOT / "tests/test_data/laya_synthetic_dataset_starter/cases.jsonl"
DEFAULT_DRAFTS = ROOT / "tests/test_data/laya_synthetic_dataset_starter/draft_responses.jsonl"
DEFAULT_EMAILS = ROOT / "tests/test_data/laya_synthetic_dataset_starter/emails.jsonl"

LOGS_BUCKET  = os.environ.get("RESULTS_BUCKET", "insuremail-ai-dev-logs")
REGION       = os.environ.get("AWS_REGION", "us-east-1")
JUDGE_MODEL  = "mistral.mistral-7b-instruct-v0:2"  # LLM judge for response quality

s3_client = boto3.client("s3",             region_name=REGION)
bedrock   = boto3.client("bedrock-runtime", region_name=REGION)

HEDGE_PHRASES = [
    "please", "kindly", "if you have", "do not hesitate", "thank you",
    "we understand", "we apologise", "we apologize", "feel free",
    "should you", "for your convenience",
]


# ── Dataset helpers ────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> List[Dict]:
    records = []
    if not path.exists():
        return records
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def find_latest_assessment() -> Optional[Path]:
    files = sorted(RESULTS_DIR.glob("stepfn_assessment_*.json"), reverse=True)
    return files[0] if files else None


def llm_judge_response(gold: str, pred: str) -> Optional[float]:
    """
    Use Claude 3 Haiku as a judge to score the predicted response vs gold.
    Returns a float 0.0–1.0 (or None on failure).
    Criteria: relevance, accuracy, completeness, professionalism.
    """
    if not gold or not pred:
        return None
    prompt = (
        "You are an expert evaluator for insurance customer service responses.\n\n"
        f"Gold standard response:\n\"\"\"\n{gold[:1500]}\n\"\"\"\n\n"
        f"Generated response:\n\"\"\"\n{pred[:1500]}\n\"\"\"\n\n"
        "Rate the generated response on a scale of 0.0 to 1.0 based on:\n"
        "- Relevance: does it address the same issue?\n"
        "- Accuracy: are the facts/positions consistent with the gold?\n"
        "- Completeness: are the key points covered?\n"
        "- Professionalism: appropriate tone for insurance customer service?\n\n"
        "Respond ONLY with a JSON object: {\"score\": <float 0.0-1.0>, \"reason\": \"<one sentence>\"}"
    )
    try:
        resp = bedrock.invoke_model(
            modelId=JUDGE_MODEL,
            body=json.dumps({
                "prompt":      f"<s>[INST] {prompt} [/INST]",
                "max_tokens":  128,
                "temperature": 0.0,
            }),
            contentType="application/json",
            accept="application/json",
        )
        raw  = json.loads(resp["body"].read())
        text = raw["outputs"][0]["text"]
        match = re.search(r'"score"\s*:\s*([0-9.]+)', text)
        if match:
            return round(min(1.0, max(0.0, float(match.group(1)))), 4)
    except Exception:
        pass
    return None


# ── Build join maps ────────────────────────────────────────────────────────────

def build_gold_response_map(cases: List[Dict], drafts: List[Dict]) -> Dict[str, str]:
    """Map email_id → gold generated_reply."""
    draft_by_id = {d["draft_response_id"]: d for d in drafts}
    gold: Dict[str, str] = {}
    for case in cases:
        eid      = case.get("email_id", "")
        draft_id = case.get("draft_response_id", "")
        draft    = draft_by_id.get(draft_id, {})
        reply    = draft.get("generated_reply", "")
        if eid and reply:
            gold[eid] = reply
    return gold


def build_intent_map(emails: List[Dict]) -> Dict[str, str]:
    return {e["email_id"]: e.get("customer_intent", "") for e in emails}


def build_human_review_map(emails: List[Dict]) -> Dict[str, bool]:
    return {e["email_id"]: bool(e.get("requires_human_review", False)) for e in emails}


# ── Scoring ────────────────────────────────────────────────────────────────────

def evaluate(
    per_email: List[Dict],
    gold_response_map: Dict[str, str],
    intent_map: Dict[str, str],
    human_review_map: Dict[str, bool],
) -> Dict:
    results = []

    for r in per_email:
        laya_id  = r.get("laya_email_id", "")
        pred_txt = r.get("response_text", "")
        gold_txt = gold_response_map.get(laya_id, "")
        intent   = intent_map.get(laya_id, r.get("gold_intent", ""))
        action   = r.get("action", "")
        gold_human = human_review_map.get(laya_id, r.get("gold_requires_human", False))

        llm_score = llm_judge_response(gold_txt, pred_txt) if gold_txt and pred_txt else None
        hedge     = any(ph in pred_txt.lower() for ph in HEDGE_PHRASES) if pred_txt else False

        results.append({
            "email_id":         laya_id,
            "intent":           intent,
            "has_response":     bool(pred_txt),
            "has_gold":         bool(gold_txt),
            "llm_judge_score":  llm_score,
            "hedge":            hedge,
            "action":           action,
            "gold_human_review": gold_human,
        })

    # Aggregate metrics
    with_response  = [r for r in results if r["has_response"]]
    with_gold_pair = [r for r in results if r["has_response"] and r["has_gold"]]
    judge_vals = [r["llm_judge_score"] for r in with_gold_pair if r["llm_judge_score"] is not None]
    avg_llm_score = round(sum(judge_vals) / len(judge_vals), 4) if judge_vals else None

    hedge_rate = (
        sum(1 for r in with_response if r["hedge"]) / len(with_response)
        if with_response else 0.0
    )

    human_needed = [r for r in results if r["gold_human_review"]]
    correctly_escalated = [r for r in human_needed if r["action"] in ("human_review", "escalate")]
    escalation_agreement = (
        round(len(correctly_escalated) / len(human_needed), 4)
        if human_needed else None
    )

    # Per-intent avg LLM judge score
    by_intent: Dict[str, List[float]] = defaultdict(list)
    for r in with_gold_pair:
        if r["llm_judge_score"] is not None:
            by_intent[r["intent"]].append(r["llm_judge_score"])
    per_intent_f1 = {
        intent: round(sum(vals) / len(vals), 4)
        for intent, vals in by_intent.items()
    }

    return {
        "avg_llm_judge_score":    avg_llm_score,
        "judge_model":            JUDGE_MODEL,
        "hedge_rate":             round(hedge_rate, 4),
        "escalation_agreement":   escalation_agreement,
        "response_coverage_rate": round(len(with_response) / len(results), 4) if results else 0.0,
        "n_evaluated":            len(results),
        "n_with_response":        len(with_response),
        "n_with_gold_pair":       len(with_gold_pair),
        "n_human_review_gold":    len(human_needed),
        "per_intent_f1":          per_intent_f1,
        "per_email":              results,
    }


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_report(assessment_path: str, run_summary: Dict, m: Dict) -> None:
    SEP = "=" * 60
    print(f"\n{SEP}")
    print("  Response Generation Evaluation — InsureMail AI")
    print(SEP)
    print(f"  Source   : {assessment_path}")
    print(f"  Records  : {m['n_evaluated']}  |  With response: {m['n_with_response']}  |  With gold pair: {m['n_with_gold_pair']}")

    status = "PASSED" if (m["escalation_agreement"] or 0) >= 0.70 else "FAILED"
    print(f"\n  Avg LLM Judge Score   : {m['avg_llm_judge_score'] or 'N/A'}  (model: {m['judge_model']})")
    print(f"  Hedge Rate            : {m['hedge_rate']:.4f}")
    print(f"  Escalation Agreement  : {m['escalation_agreement'] or 'N/A'}  [{status}]  (threshold=0.70)")
    print(f"  Response Coverage Rate: {m['response_coverage_rate']:.4f}")

    if m["per_intent_f1"]:
        print(f"\n  Per-Intent Token-Overlap F1:")
        for intent, f1 in sorted(m["per_intent_f1"].items()):
            bar = "█" * int(f1 * 20)
            print(f"    {intent:<35}  {f1:.3f}  {bar}")
    print(SEP)


def upload_to_s3(local_path: str) -> None:
    try:
        with open(local_path, "rb") as fh:
            s3_client.put_object(
                Bucket=LOGS_BUCKET,
                Key="eval_reports/response_eval_latest.json",
                Body=fh.read(),
                ContentType="application/json",
            )
        print(f"Uploaded to s3://{LOGS_BUCKET}/eval_reports/response_eval_latest.json")
    except Exception as e:
        print(f"[warn] S3 upload skipped: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Response generation post-hoc evaluation.")
    p.add_argument("--assessment", default=None, help="Path to stepfn_assessment JSON (default: latest in results/)")
    p.add_argument("--cases",      default=str(DEFAULT_CASES))
    p.add_argument("--drafts",     default=str(DEFAULT_DRAFTS))
    p.add_argument("--emails",     default=str(DEFAULT_EMAILS))
    p.add_argument("--output",     default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Load assessment
    assessment_path = args.assessment
    if not assessment_path:
        latest = find_latest_assessment()
        if not latest:
            print("ERROR: No stepfn_assessment_*.json found in results/. Run run_stepfn_assessment.py first.")
            raise SystemExit(1)
        assessment_path = str(latest)

    print(f"Loading assessment: {assessment_path}")
    with open(assessment_path, encoding="utf-8") as fh:
        assessment = json.load(fh)

    per_email = assessment.get("per_email_results", [])
    if not per_email:
        print("ERROR: assessment has no per_email_results.")
        raise SystemExit(1)

    print(f"Loaded {len(per_email)} email results from assessment.")

    cases  = load_jsonl(Path(args.cases))
    drafts = load_jsonl(Path(args.drafts))
    emails = load_jsonl(Path(args.emails))

    gold_response_map = build_gold_response_map(cases, drafts)
    intent_map        = build_intent_map(emails)
    human_review_map  = build_human_review_map(emails)

    print(f"Gold responses available for {len(gold_response_map)} emails.")

    m = evaluate(per_email, gold_response_map, intent_map, human_review_map)

    run_summary = {
        "assessment_source": assessment_path,
        "assessment_run_id": assessment.get("assessment_metadata", {}).get("run_id", ""),
        "n_pipeline_emails": len(per_email),
    }

    print_report(assessment_path, run_summary, m)

    report = {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "assessment_source":    assessment_path,
        "run_summary":          run_summary,
        "response_generation":  {k: v for k, v in m.items() if k != "per_email"},
        "per_email_results":    m["per_email"],
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.output or str(RESULTS_DIR / f"response_eval_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"\nResults written to: {out_path}")

    upload_to_s3(out_path)


if __name__ == "__main__":
    main()
