"""
scripts/load_knowledge_docs.py

Reads knowledge_docs.jsonl, generates Titan Embeddings V2 vectors for each
document, and inserts the records into the existing DynamoDB embeddings table.

Follows the exact same schema used by the rag_ingestion Lambda so that the
RAG retrieval Lambda can query this data without any changes.

DynamoDB item schema:
    doc_id    (PK, str)  — from source field: "doc_id" | "id" | auto-generated
    doc_type  (str)      — from source field: "doc_type" | "type" | "general"
    content   (str)      — from source field: "content" | "text" | "body"
    embedding (str)      — JSON-encoded list[float], 1024-dim Titan V2 vector
    metadata  (dict)     — source_key, chunk_index, content_length, embedding_dim
    timestamp (str)      — ISO 8601 UTC

Usage:
    python scripts/load_knowledge_docs.py \
        --file   data/knowledge_docs.jsonl \
        --table  insuremail-prod-embeddings \
        --region eu-west-1 \
        [--dry-run]
"""

import argparse
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Tuple

import boto3
from botocore.exceptions import ClientError

# ── Config ────────────────────────────────────────────────────────────────────
TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIM      = 1024
EMBED_WORKERS  = 6    # parallel Bedrock embedding calls
SOURCE_FILE    = "knowledge_docs.jsonl"

# Field name fallbacks: try these in order when reading each source record
_CONTENT_FIELDS = ("chunk_text", "content", "text", "body", "document", "chunk")
_DOCID_FIELDS   = ("chunk_id", "doc_id", "id", "document_id")
_DOCTYPE_FIELDS = ("doc_type", "type", "category", "source_type")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load knowledge_docs.jsonl into DynamoDB embeddings table"
    )
    parser.add_argument("--file",   default=SOURCE_FILE,  help="Path to knowledge_docs.jsonl")
    parser.add_argument("--table",  required=True,        help="DynamoDB embeddings table name")
    parser.add_argument("--region", default="us-east-1",  help="AWS region (default: us-east-1)")
    parser.add_argument("--dry-run", action="store_true", help="Parse + print without writing")
    args = parser.parse_args()

    # ── Load records ──────────────────────────────────────────────────────────
    records = _load_jsonl(args.file)
    if not records:
        print(f"No records found in {args.file!r}. Exiting.")
        sys.exit(0)

    print(f"Loaded {len(records)} records from {args.file!r}")

    # ── Normalise to internal schema ──────────────────────────────────────────
    normalised = [_normalise(r, i) for i, r in enumerate(records)]

    if args.dry_run:
        print(f"[DRY RUN] Would embed and insert {len(normalised)} documents:")
        for doc in normalised:
            print(f"  {doc['doc_id']} ({doc['doc_type']}) — {len(doc['content'])} chars")
        sys.exit(0)

    # ── Embed ─────────────────────────────────────────────────────────────────
    bedrock = boto3.client("bedrock-runtime", region_name=args.region)
    print(f"Embedding {len(normalised)} documents with {EMBED_WORKERS} workers …")
    embedded = _embed_all(normalised, bedrock)

    # ── Write to DynamoDB ─────────────────────────────────────────────────────
    dynamo = boto3.resource("dynamodb", region_name=args.region)
    table  = dynamo.Table(args.table)
    count  = _batch_write(embedded, table, source_file=args.file)

    print(f"Done. {count}/{len(records)} documents written to '{args.table}'.")


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

def _normalise(record: Dict[str, Any], index: int) -> Dict[str, Any]:
    """
    Map raw JSONL record to internal schema, handling varied field names.
    Falls back gracefully when expected fields are missing.
    """
    # Content (required)
    content = ""
    for field in _CONTENT_FIELDS:
        if field in record and str(record[field]).strip():
            content = str(record[field]).strip()
            break
    if not content:
        # Last resort: JSON-encode the whole record as content
        content = json.dumps(record)

    # Doc ID
    doc_id = ""
    for field in _DOCID_FIELDS:
        if field in record and str(record[field]).strip():
            doc_id = str(record[field]).strip()
            break
    if not doc_id:
        doc_id = f"kb_doc_{index:06d}_{uuid.uuid4().hex[:8]}"

    # Doc type
    doc_type = "general"
    for field in _DOCTYPE_FIELDS:
        if field in record and str(record[field]).strip():
            doc_type = str(record[field]).strip().lower()
            break

    # Carry through any extra metadata fields
    skip_fields = set(_CONTENT_FIELDS) | set(_DOCID_FIELDS) | set(_DOCTYPE_FIELDS)
    extra_meta  = {k: v for k, v in record.items() if k not in skip_fields}

    return {
        "doc_id":   doc_id,
        "doc_type": doc_type,
        "content":  content,
        "metadata": extra_meta,
        "index":    index,
    }


# ── Embedding ─────────────────────────────────────────────────────────────────

def _embed_all(
    docs: List[Dict[str, Any]],
    bedrock_client,
) -> List[Dict[str, Any]]:
    """
    Generate Titan Embeddings V2 vectors for all documents in parallel.
    Failed embeddings are logged and skipped.
    """
    results = []

    def embed_one(doc: Dict[str, Any]) -> Dict[str, Any]:
        text      = doc["content"][:8000]   # Titan V2 max input
        embedding = _call_titan(text, bedrock_client)
        return {**doc, "embedding": json.dumps(embedding)}

    with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as ex:
        futures = {ex.submit(embed_one, d): d["doc_id"] for d in docs}
        for future in as_completed(futures):
            doc_id = futures[future]
            try:
                results.append(future.result())
                print(f"  Embedded {doc_id}")
            except Exception as e:
                print(f"  ERROR embedding {doc_id}: {e}", file=sys.stderr)

    return results


def _call_titan(text: str, client) -> List[float]:
    """Invoke Amazon Titan Embeddings V2 and return a 1024-dim normalised vector."""
    response = client.invoke_model(
        modelId=TITAN_MODEL_ID,
        body=json.dumps({
            "inputText": text,
            "dimensions": EMBED_DIM,
            "normalize": True,
        }),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


# ── DynamoDB writer ───────────────────────────────────────────────────────────

def _batch_write(
    docs: List[Dict[str, Any]],
    table,
    source_file: str,
) -> int:
    """
    Write embedded documents to DynamoDB using batch_writer.
    Uses put_item semantics — safe to re-run (idempotent by doc_id PK).
    Returns the number of items written.
    """
    now   = datetime.utcnow().isoformat() + "Z"
    count = 0

    with table.batch_writer() as batch:
        for doc in docs:
            batch.put_item(Item={
                "doc_id":    doc["doc_id"],
                "doc_type":  doc["doc_type"],
                "content":   doc["content"],
                "embedding": doc["embedding"],   # JSON string of float list
                "metadata":  {
                    **doc.get("metadata", {}),
                    "source_key":     source_file,
                    "chunk_index":    doc["index"],
                    "content_length": len(doc["content"]),
                    "embedding_dim":  EMBED_DIM,
                },
                "timestamp": now,
            })
            count += 1

    return count


if __name__ == "__main__":
    main()
