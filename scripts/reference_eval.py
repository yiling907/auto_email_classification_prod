#!/usr/bin/env python3
"""
Reference-based RAG evaluation script.

Runs the full retrieval + generation pipeline against rag_eval_dataset.json
and scores each response with deterministic metrics (no LLM judge).

Usage:
    python scripts/reference_eval.py [--dry-run] [--dataset PATH]

Metrics (no LLM judge):
    key_fact_recall     -- fraction of expected_key_facts found in response
    hallucination_flag  -- response contains numbers not present in context
    out_of_scope_refusal-- model correctly refuses non-RAG queries
    response_length_ok  -- response within [50, 600] chars
    hedge_present       -- response contains required hedge phrase

Composite score (0-1):
    0.40 * key_fact_recall
    + 0.35 * (1 - hallucination_rate)
    + 0.25 * out_of_scope_refusal_rate

Exit code 0 if composite >= 0.75, else 1 (use as CI gate).
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

import boto3

# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
DATASET_DEFAULT = ROOT / 'tests' / 'test_data' / 'rag_eval_dataset.json'

RETRIEVAL_LAMBDA  = 'insuremail-ai-dev-rag-retrieval'
GENERATION_LAMBDA = 'insuremail-ai-dev-claude-response'

PASS_THRESHOLD = 0.75   # composite score required to exit 0

_NUMBER_RE    = re.compile(r'\b\d[\d,./€$£%\-]+\b')
_HEDGE_PHRASES = [
    'scheme rules', 'benefit table', 'contact laya', 'please refer',
    '1890', 'member area', "don't have enough information",
]
_REFUSAL_PHRASES = [
    "don't have enough information", "cannot answer", "contact laya",
    "outside my knowledge", "not able to answer",
]


# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    query_id:             str
    query:                str
    response:             str
    retrieved_docs:       int
    key_fact_recall:      float
    hallucination_flag:   bool
    out_of_scope_refused: bool
    response_length_ok:   bool
    hedge_present:        bool
    composite:            float = field(init=False)

    def __post_init__(self):
        self.composite = round(
            0.40 * self.key_fact_recall +
            0.35 * (0.0 if self.hallucination_flag else 1.0) +
            0.25 * (1.0 if self.out_of_scope_refused else 0.5),
            4,
        )


def evaluate_one(
    record: dict,
    response: str,
    context: str,
) -> EvalResult:
    response_lower = response.lower()

    # Key fact recall
    facts  = record.get('expected_key_facts', [])
    recall = (
        sum(f.lower() in response_lower for f in facts) / len(facts)
        if facts else 1.0
    )

    # Hallucination: numbers in response not grounded in context
    resp_nums = set(_NUMBER_RE.findall(response))
    ctx_nums  = set(_NUMBER_RE.findall(context))
    hallucinated = bool(resp_nums - ctx_nums)

    # Out-of-scope refusal
    if not record['is_known_in_rag']:
        refused = any(p in response_lower for p in _REFUSAL_PHRASES)
    else:
        refused = True   # not applicable — count as pass

    length_ok = 50 <= len(response) <= 600
    hedge     = any(p in response_lower for p in _HEDGE_PHRASES)

    return EvalResult(
        query_id             = record['id'],
        query                = record['query'],
        response             = response[:200] + ('...' if len(response) > 200 else ''),
        retrieved_docs       = 0,   # filled in by caller
        key_fact_recall      = round(recall, 4),
        hallucination_flag   = hallucinated,
        out_of_scope_refused = refused,
        response_length_ok   = length_ok,
        hedge_present        = hedge,
    )


# ---------------------------------------------------------------------------

def call_retrieval(client, query: str, dry_run: bool) -> tuple[list, str]:
    if dry_run:
        return [], ''
    resp = client.invoke(
        FunctionName=RETRIEVAL_LAMBDA,
        Payload=json.dumps({'email_text': query, 'top_k': 3}).encode(),
    )
    result = json.loads(resp['Payload'].read())
    docs   = result.get('retrieved_documents', [])
    context = ' '.join(d.get('content', '') for d in docs)
    return docs, context


def call_generation(client, query: str, docs: list, dry_run: bool) -> str:
    if dry_run:
        return f"[DRY RUN] Would generate response for: {query[:60]}"
    resp = client.invoke(
        FunctionName=GENERATION_LAMBDA,
        Payload=json.dumps({
            'email_body':    query,
            'subject':       '',
            'rag_documents': docs,
        }).encode(),
    )
    result = json.loads(resp['Payload'].read())
    return result.get('response_text', '')


# ---------------------------------------------------------------------------

def run(dataset_path: Path, dry_run: bool) -> int:
    dataset = json.loads(dataset_path.read_text())
    lambda_client = boto3.client('lambda', region_name='us-east-1')

    results: List[EvalResult] = []

    print(f"\nRunning reference eval on {len(dataset)} records "
          f"{'[DRY RUN]' if dry_run else ''}\n{'='*60}")

    for record in dataset:
        print(f"  [{record['id']}] {record['query'][:60]}")
        docs, context = call_retrieval(lambda_client, record['query'], dry_run)
        response      = call_generation(lambda_client, record['query'], docs, dry_run)
        result        = evaluate_one(record, response, context)
        result.retrieved_docs = len(docs)
        results.append(result)

        status = 'PASS' if result.composite >= 0.60 else 'FAIL'
        print(
            f"         recall={result.key_fact_recall:.2f} "
            f"hallucinated={result.hallucination_flag} "
            f"composite={result.composite:.2f} [{status}]"
        )

    # Aggregate
    n = len(results)
    agg = {
        'total':                    n,
        'avg_key_fact_recall':      round(sum(r.key_fact_recall for r in results) / n, 4),
        'hallucination_rate':       round(sum(r.hallucination_flag for r in results) / n, 4),
        'out_of_scope_refusal_rate':round(sum(r.out_of_scope_refused for r in results) / n, 4),
        'response_length_ok_rate':  round(sum(r.response_length_ok for r in results) / n, 4),
        'hedge_rate':               round(sum(r.hedge_present for r in results) / n, 4),
        'composite_score':          round(
            0.40 * sum(r.key_fact_recall for r in results) / n +
            0.35 * (1 - sum(r.hallucination_flag for r in results) / n) +
            0.25 * sum(r.out_of_scope_refused for r in results) / n,
            4,
        ),
    }

    print(f"\n{'='*60}")
    print(f"AGGREGATE RESULTS")
    print(f"{'='*60}")
    for k, v in agg.items():
        print(f"  {k:<35} {v}")

    passed = agg['composite_score'] >= PASS_THRESHOLD
    print(f"\n{'PASSED' if passed else 'FAILED'} "
          f"(composite={agg['composite_score']:.4f}, threshold={PASS_THRESHOLD})")

    # Save report
    report_path = ROOT / 'results' / 'reference_eval_report.json'
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps({
        'aggregate': agg,
        'results':   [asdict(r) for r in results],
    }, indent=2))
    print(f"Report saved: {report_path}")

    return 0 if passed else 1


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Reference-based RAG evaluation')
    parser.add_argument('--dry-run', action='store_true',
                        help='Skip Lambda calls, use placeholder responses')
    parser.add_argument('--dataset', type=Path, default=DATASET_DEFAULT,
                        help='Path to eval dataset JSON')
    args = parser.parse_args()

    sys.exit(run(args.dataset, args.dry_run))
