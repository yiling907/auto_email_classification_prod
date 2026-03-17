"""
scripts/load_customers.py

Reads customers.jsonl and inserts all customer records into the DynamoDB
Customers table created by the storage Terraform module.

Idempotent: uses put_item (upsert by customer_id PK), safe to re-run.

DynamoDB table: {project_name}-{environment}-customers
Primary key:    customer_id (string)

Usage:
    python scripts/load_customers.py \
        --file   data/customers.jsonl \
        --table  insuremail-prod-customers \
        --region eu-west-1 \
        [--dry-run]
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError

# ── Config ────────────────────────────────────────────────────────────────────
SOURCE_FILE  = "customers.jsonl"
BATCH_SIZE   = 25    # DynamoDB batch_writer limit

# Field name fallbacks for customer_id
_CUSTOMER_ID_FIELDS = ("customer_id", "id", "member_id", "user_id", "policy_holder_id")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load customers.jsonl into DynamoDB Customers table"
    )
    parser.add_argument("--file",    default=SOURCE_FILE, help="Path to customers.jsonl")
    parser.add_argument("--table",   required=True,       help="DynamoDB customers table name")
    parser.add_argument("--region",  default="eu-west-1", help="AWS region (default: eu-west-1)")
    parser.add_argument("--dry-run", action="store_true", help="Parse + print without writing")
    args = parser.parse_args()

    # ── Load records ──────────────────────────────────────────────────────────
    records = _load_jsonl(args.file)
    if not records:
        print(f"No records found in {args.file!r}. Exiting.")
        sys.exit(0)

    print(f"Loaded {len(records)} customer records from {args.file!r}")

    # ── Normalise ─────────────────────────────────────────────────────────────
    normalised, skipped = _normalise_all(records)
    if skipped:
        print(f"  WARNING: {skipped} records skipped (no usable customer_id)")
    print(f"  {len(normalised)} records ready to insert")

    if args.dry_run:
        print(f"[DRY RUN] Would insert {len(normalised)} records into '{args.table}':")
        for r in normalised[:5]:
            print(f"  {r.get('customer_id')} — {r.get('name') or r.get('customer_name', '')}")
        if len(normalised) > 5:
            print(f"  … and {len(normalised) - 5} more")
        sys.exit(0)

    # ── Insert ────────────────────────────────────────────────────────────────
    dynamo = boto3.resource("dynamodb", region_name=args.region)
    table  = dynamo.Table(args.table)

    written, errors = _batch_insert(normalised, table)
    print(f"Done. {written} records written, {errors} errors.")
    if errors:
        sys.exit(1)


# ── JSONL loader ──────────────────────────────────────────────────────────────

def _load_jsonl(filepath: str) -> List[Dict[str, Any]]:
    """Read a JSONL file and return a list of parsed JSON objects."""
    records = []
    try:
        with open(filepath, encoding="utf-8") as fh:
            for line_num, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"  WARNING: skipping line {line_num} (JSON parse error: {e})")
    except FileNotFoundError:
        print(f"ERROR: File not found: {filepath!r}", file=sys.stderr)
        sys.exit(1)
    return records


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalise_all(
    records: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], int]:
    """
    Ensure every record has a customer_id string PK.
    Returns (normalised_records, skipped_count).
    """
    normalised = []
    skipped    = 0
    now        = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    for record in records:
        # Resolve customer_id from common field name variants
        customer_id = ""
        for field in _CUSTOMER_ID_FIELDS:
            if field in record and str(record.get(field, "")).strip():
                customer_id = str(record[field]).strip()
                break

        if not customer_id:
            skipped += 1
            continue

        # Build a clean item with customer_id guaranteed as PK
        item = _dynamo_safe({**record, "customer_id": customer_id})
        # Attach load timestamp if not present
        item.setdefault("loaded_at", now)
        normalised.append(item)

    return normalised, skipped


# ── DynamoDB type safety ───────────────────────────────────────────────────────

def _dynamo_safe(obj: Any) -> Any:
    """
    Recursively make a Python object safe for DynamoDB:
      • float  → Decimal (DynamoDB rejects Python floats)
      • None   → removed (DynamoDB rejects null in some contexts; skip empty)
      • set    → list    (DynamoDB StringSet/NumberSet handled separately)
    """
    if isinstance(obj, dict):
        return {k: _dynamo_safe(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_dynamo_safe(v) for v in obj]
    if isinstance(obj, float):
        try:
            return Decimal(str(obj))
        except InvalidOperation:
            return str(obj)
    if isinstance(obj, set):
        return [_dynamo_safe(v) for v in obj]
    return obj


# ── Batch insert ──────────────────────────────────────────────────────────────

def _batch_insert(
    records: List[Dict[str, Any]],
    table,
) -> tuple[int, int]:
    """
    Write records to DynamoDB using batch_writer (auto-batches at 25 items).
    put_item semantics: inserts new records and overwrites existing ones with
    the same customer_id — safe and idempotent.

    Returns (written_count, error_count).
    """
    written = 0
    errors  = 0

    with table.batch_writer() as batch:
        for record in records:
            try:
                batch.put_item(Item=record)
                written += 1
            except ClientError as e:
                errors += 1
                cid = record.get("customer_id", "?")
                print(
                    f"  ERROR inserting customer {cid!r}: "
                    f"{e.response['Error']['Code']} — {e.response['Error']['Message']}",
                    file=sys.stderr,
                )
            except Exception as e:
                errors += 1
                cid = record.get("customer_id", "?")
                print(f"  ERROR inserting customer {cid!r}: {e}", file=sys.stderr)

    return written, errors


if __name__ == "__main__":
    main()
