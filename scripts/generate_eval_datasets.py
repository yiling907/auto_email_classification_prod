#!/usr/bin/env python3
"""
Generate evaluation datasets from the laya synthetic dataset.

Joins emails → cases → draft_responses and produces two 100-record JSONL files:
  - laya_model_eval.jsonl  : general model QA, stratified by customer_intent
  - laya_rag_eval.jsonl    : RAG-grounded QA, stratified by rag_context_group

Outputs land in:
  lambda/bedrock_evaluation/laya_model_eval.jsonl
  lambda/bedrock_evaluation/laya_rag_eval.jsonl

Pass --upload to also push both files to S3 under eval-datasets/.
"""
import argparse
import json
import os
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
LAYA_DIR = REPO_ROOT / "tests" / "test_data" / "laya_synthetic_dataset_starter"
OUTPUT_DIR = REPO_ROOT / "lambda" / "bedrock_evaluation"
RECORDS_PER_DATASET = 100

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> List[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save_jsonl(records: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Saved {len(records)} records → {path}")


def stratified_sample(
    records: List[dict],
    strata_key: str,
    total: int,
    seed: int = 42,
) -> List[dict]:
    """Sample `total` records stratified by `strata_key`."""
    rng = random.Random(seed)
    by_stratum: Dict[str, List[dict]] = defaultdict(list)
    for r in records:
        by_stratum[r.get(strata_key, "unknown")].append(r)

    strata = list(by_stratum.keys())
    per_stratum = max(1, total // len(strata))
    sampled: List[dict] = []

    for stratum, items in by_stratum.items():
        rng.shuffle(items)
        sampled.extend(items[:per_stratum])

    # Top up / trim to exactly `total`
    rng.shuffle(sampled)
    if len(sampled) < total:
        remaining = [r for r in records if r not in sampled]
        rng.shuffle(remaining)
        sampled.extend(remaining[: total - len(sampled)])
    return sampled[:total]


# ---------------------------------------------------------------------------
# Join & format
# ---------------------------------------------------------------------------

def build_joined_records(
    emails: List[dict],
    cases: List[dict],
    draft_responses: List[dict],
) -> List[dict]:
    """Join emails → cases → draft_responses into flat dicts."""
    case_by_email: Dict[str, dict] = {c["email_id"]: c for c in cases}
    response_by_id: Dict[str, dict] = {d["draft_response_id"]: d for d in draft_responses}

    joined = []
    for email in emails:
        eid = email["email_id"]
        case = case_by_email.get(eid)
        if not case:
            continue
        draft_id = case.get("draft_response_id", "")
        draft = response_by_id.get(draft_id)
        if not draft:
            continue
        joined.append({
            # Email fields
            "email_id":          eid,
            "subject":           email.get("subject", ""),
            "body_text":         email.get("body_text", ""),
            "customer_intent":   email.get("customer_intent", ""),
            "requires_human_review": email.get("requires_human_review", False),
            "gold_route_team":   email.get("gold_route_team", ""),
            "urgency":           email.get("urgency", ""),
            # Case fields
            "case_id":           case.get("case_id", ""),
            "rag_context_group": case.get("rag_context_group", ""),
            "route_team":        case.get("route_team", ""),
            # Draft response
            "generated_reply":   draft.get("generated_reply", ""),
            "grounded_doc_ids":  draft.get("grounded_doc_ids", []),
        })
    return joined


MODEL_EVAL_PROMPT_TEMPLATE = (
    "You are a helpful insurance customer service assistant. "
    "Read the following customer email and compose a professional, accurate response.\n\n"
    "Subject: {subject}\n\n"
    "Email:\n{body_text}"
)

RAG_EVAL_PROMPT_TEMPLATE = (
    "You are a helpful insurance customer service assistant. "
    "Use only the knowledge base context implied by the topic '{rag_context_group}' "
    "to respond to the following customer email. Ground your answer in policy facts.\n\n"
    "Subject: {subject}\n\n"
    "Email:\n{body_text}"
)


def format_model_eval_record(r: dict) -> dict:
    return {
        "prompt": MODEL_EVAL_PROMPT_TEMPLATE.format(
            subject=r["subject"],
            body_text=r["body_text"],
        ),
        "referenceResponse": r["generated_reply"],
        "category": r["customer_intent"],
        # Keep metadata for local eval script
        "email_id":              r["email_id"],
        "gold_route_team":       r["gold_route_team"],
        "requires_human_review": r["requires_human_review"],
    }


def format_rag_eval_record(r: dict) -> dict:
    return {
        "prompt": RAG_EVAL_PROMPT_TEMPLATE.format(
            rag_context_group=r["rag_context_group"],
            subject=r["subject"],
            body_text=r["body_text"],
        ),
        "referenceResponse": r["generated_reply"],
        "category": r["rag_context_group"],
        # Keep metadata
        "email_id":              r["email_id"],
        "gold_route_team":       r["gold_route_team"],
        "requires_human_review": r["requires_human_review"],
        "customer_intent":       r["customer_intent"],
    }


# ---------------------------------------------------------------------------
# S3 upload
# ---------------------------------------------------------------------------

def upload_to_s3(files: Dict[str, Path], bucket: Optional[str] = None) -> None:
    import boto3
    if not bucket:
        bucket = os.environ.get("KNOWLEDGE_BASE_BUCKET")
    if not bucket:
        raise ValueError("S3 bucket not specified. Set KNOWLEDGE_BASE_BUCKET env var or pass --bucket.")
    s3 = boto3.client("s3")
    for s3_key, local_path in files.items():
        s3.upload_file(str(local_path), bucket, s3_key)
        print(f"  Uploaded → s3://{bucket}/{s3_key}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate laya evaluation datasets")
    parser.add_argument("--records", type=int, default=RECORDS_PER_DATASET,
                        help="Records per output file (default 100)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--upload", action="store_true", help="Upload to S3 after generation")
    parser.add_argument("--bucket", default=None, help="S3 bucket (overrides KNOWLEDGE_BASE_BUCKET env)")
    args = parser.parse_args()

    print("Loading laya dataset files...")
    emails = load_jsonl(LAYA_DIR / "emails.jsonl")
    cases = load_jsonl(LAYA_DIR / "cases.jsonl")
    drafts = load_jsonl(LAYA_DIR / "draft_responses.jsonl")

    print(f"  emails={len(emails)}, cases={len(cases)}, drafts={len(drafts)}")

    joined = build_joined_records(emails, cases, drafts)
    print(f"  Joined records: {len(joined)}")

    # --- Model eval dataset (stratified by customer_intent) ---
    model_sample = stratified_sample(joined, "customer_intent", args.records, seed=args.seed)
    model_records = [format_model_eval_record(r) for r in model_sample]

    # --- RAG eval dataset (stratified by rag_context_group) ---
    rag_sample = stratified_sample(joined, "rag_context_group", args.records, seed=args.seed + 1)
    rag_records = [format_rag_eval_record(r) for r in rag_sample]

    # Save
    model_path = OUTPUT_DIR / "laya_model_eval.jsonl"
    rag_path   = OUTPUT_DIR / "laya_rag_eval.jsonl"

    print(f"\nGenerating datasets ({args.records} records each)...")
    save_jsonl(model_records, model_path)
    save_jsonl(rag_records, rag_path)

    # Verify intent distribution
    intents = [r["category"] for r in model_records]
    print(f"\nIntent distribution (model_eval):")
    for intent, count in sorted(
        {i: intents.count(i) for i in set(intents)}.items(), key=lambda x: -x[1]
    ):
        print(f"    {intent:<30} {count}")

    if args.upload:
        print("\nUploading datasets to S3...")
        upload_to_s3(
            {
                "eval-datasets/laya_model_eval.jsonl": model_path,
                "eval-datasets/laya_rag_eval.jsonl": rag_path,
            },
            bucket=args.bucket,
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
