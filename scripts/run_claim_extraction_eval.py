"""
run_claim_extraction_eval.py
============================
Evaluation script for the InsureMail AI Laya Healthcare Out-patient Claim Form
extraction pipeline.

For each record in the gold dataset this script:
  1. Imports _extract_via_bedrock from the email_parser Lambda module.
  2. Passes the simulated PDF text as a text_chunk to the extractor.
  3. Compares the extracted fields against gold_fields using field-level metrics.
  4. Prints a structured summary table and writes a JSON results file.

Usage
-----
  python scripts/run_claim_extraction_eval.py [OPTIONS]

Options
-------
  --dataset  Path to JSONL gold dataset (default: tests/test_data/claim_forms/claim_form_gold_dataset.jsonl)
  --limit    Run only the first N records
  --output   Path to output JSON report (default: results/claim_extraction_eval_<timestamp>.json)

Requirements
------------
  pip install boto3 botocore

The script imports directly from lambda/email_parser/lambda_function.py.
Set the EMAIL_TABLE_NAME environment variable before running (the module requires it
at import time); the variable is set automatically to a dummy value if absent.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("claim_eval")

# ── Module bootstrap — must happen before lambda import ───────────────────────
os.environ.setdefault("EMAIL_TABLE_NAME", "claim-eval-dummy")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAMBDA_PATH = os.path.join(_REPO_ROOT, "lambda", "email_parser")
if _LAMBDA_PATH not in sys.path:
    sys.path.insert(0, _LAMBDA_PATH)

# Clear any cached module from a previous import
sys.modules.pop("lambda_function", None)

try:
    from lambda_function import _extract_via_bedrock  # type: ignore
    _IMPORT_OK = True
except Exception as _import_err:
    logger.error("Failed to import _extract_via_bedrock: %s", _import_err)
    _IMPORT_OK = False

# ── Constants ──────────────────────────────────────────────────────────────────
DEFAULT_DATASET = os.path.join(
    _REPO_ROOT,
    "tests", "test_data", "claim_forms", "claim_form_gold_dataset.jsonl"
)
DEFAULT_OUTPUT_DIR = os.path.join(_REPO_ROOT, "results")

# String fields to evaluate with exact + partial match
STRING_FIELDS: List[str] = [
    "membership_no",
    "title",
    "surname",
    "forenames",
    "date_of_birth",
    "telephone",
    "correspondence_address",
    "mri_date",
    "mri_reason_for_referral",
    "mri_centre",
    "mri_procedure",
    "mri_referring_gp",
    "mri_consultant_code",
    "accident_date",
    "accident_description",
    "third_party_details",
    "dental_injury_date",
    "dental_injury_place",
    "dental_injury_description",
    "dental_treatment_start",
    "dental_treatment_end",
    "account_holder_name",
    "account_number",
    "bank_sort_code",
    "bank_name_address",
    "declaration_date",
]

# Boolean fields (expenses_recoverable, recovery_via_solicitor, recovery_via_piab)
BOOL_FIELDS: List[str] = [
    "expenses_recoverable",
    "recovery_via_solicitor",
    "recovery_via_piab",
]

# Numeric fields (within 5% tolerance)
NUMERIC_FIELDS: List[str] = [
    "receipts_total_cost",
    "dental_cost",
]

# Scenario display labels
SCENARIO_LABELS: Dict[str, str] = {
    "gp_physio_receipts": "GP/physio receipts",
    "accident_section": "Accident section",
    "dental_emergency": "Dental emergency",
    "mri_scan": "MRI/scan referral",
    "dependant_claim": "Dependant claims",
    "incomplete_form": "Incomplete forms",
}

# Bedrock throttle retry settings
MAX_RETRIES = 1
RETRY_SLEEP_S = 5.0


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class GoldRecord:
    """Single gold-standard claim form record."""

    test_id: str
    scenario: str
    email: Dict[str, str]
    pdf_text: str
    gold_fields: Dict[str, Any]
    expected_intent: str
    expected_route: str


@dataclass
class FieldResult:
    """Metrics for a single extracted field across all evaluated records."""

    field_name: str
    # Counts for string fields
    tp_exact: int = 0       # gold non-null, predicted correct (exact)
    tp_partial: int = 0     # gold non-null, predicted correct (substring)
    fp: int = 0             # gold null, predicted non-null (hallucination)
    fn: int = 0             # gold non-null, predicted null/wrong
    tn: int = 0             # gold null, predicted null (correct absence)
    total_gold_present: int = 0
    total_gold_absent: int = 0

    @property
    def precision_exact(self) -> float:
        """Exact-match precision = TP_exact / (TP_exact + FP)."""
        denom = self.tp_exact + self.fp
        return self.tp_exact / denom if denom else 0.0

    @property
    def recall_exact(self) -> float:
        """Exact-match recall = TP_exact / (TP_exact + FN)."""
        denom = self.tp_exact + self.fn
        return self.tp_exact / denom if denom else 0.0

    @property
    def f1_exact(self) -> float:
        """Exact-match F1."""
        p, r = self.precision_exact, self.recall_exact
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def precision_partial(self) -> float:
        """Partial-match precision."""
        denom = self.tp_partial + self.fp
        return self.tp_partial / denom if denom else 0.0

    @property
    def recall_partial(self) -> float:
        """Partial-match recall."""
        denom = self.tp_partial + self.fn
        return self.tp_partial / denom if denom else 0.0

    @property
    def f1_partial(self) -> float:
        """Partial-match F1."""
        p, r = self.precision_partial, self.recall_partial
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def null_accuracy(self) -> float:
        """Fraction of gold-null cases correctly predicted null."""
        if not self.total_gold_absent:
            return 1.0
        return self.tn / self.total_gold_absent


@dataclass
class NumericResult:
    """Metrics for a numeric field across all evaluated records."""

    field_name: str
    within_5pct: int = 0
    total_gold_present: int = 0
    mae_sum: float = 0.0
    fp: int = 0   # gold null, predicted non-null
    tn: int = 0   # gold null, predicted null

    @property
    def accuracy(self) -> float:
        """Fraction of gold-present cases within 5% tolerance."""
        return self.within_5pct / self.total_gold_present if self.total_gold_present else 0.0

    @property
    def mae(self) -> float:
        """Mean absolute error over gold-present cases."""
        return self.mae_sum / self.total_gold_present if self.total_gold_present else 0.0


@dataclass
class ReceiptsResult:
    """Metrics for the receipts array field."""

    tp_treatment: int = 0   # treatment_type token-overlap match
    fp_treatment: int = 0
    fn_treatment: int = 0
    within_cost_5pct: int = 0
    total_receipt_rows_gold: int = 0

    @property
    def treatment_f1(self) -> float:
        """F1 for treatment_type matching."""
        p_denom = self.tp_treatment + self.fp_treatment
        r_denom = self.tp_treatment + self.fn_treatment
        p = self.tp_treatment / p_denom if p_denom else 0.0
        r = self.tp_treatment / r_denom if r_denom else 0.0
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def cost_accuracy(self) -> float:
        """Fraction of receipt rows with total_cost within 5%."""
        return (
            self.within_cost_5pct / self.total_receipt_rows_gold
            if self.total_receipt_rows_gold else 0.0
        )


@dataclass
class DependantsResult:
    """Metrics for dependants array extraction."""

    gold_present_count: int = 0       # records where gold has at least one dependant
    predicted_present_count: int = 0  # of those, how many had at least one predicted
    name_tp: int = 0
    name_fp: int = 0
    name_fn: int = 0

    @property
    def detection_recall(self) -> float:
        """Fraction of records with dependants where at least one was predicted."""
        return (
            self.predicted_present_count / self.gold_present_count
            if self.gold_present_count else 1.0
        )

    @property
    def name_f1(self) -> float:
        """Token-overlap F1 for dependant names."""
        p_denom = self.name_tp + self.name_fp
        r_denom = self.name_tp + self.name_fn
        p = self.name_tp / p_denom if p_denom else 0.0
        r = self.name_tp / r_denom if r_denom else 0.0
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class RunRecord:
    """Result for a single evaluated record."""

    test_id: str
    scenario: str
    latency_ms: int
    bedrock_called: bool
    extraction_confidence: float
    error: Optional[str] = None
    field_scores: Dict[str, bool] = field(default_factory=dict)


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_string(value: Any) -> str:
    """
    Normalize a field value for comparison.

    Strips whitespace, lowercases, collapses internal whitespace,
    and removes common punctuation variants.
    """
    if value is None:
        return ""
    s = str(value).strip().lower()
    # Collapse multiple spaces / newlines
    import re
    s = re.sub(r"\s+", " ", s)
    # Normalise Irish name punctuation: o'brien → obrien for partial match
    s = s.replace("'", "").replace("-", " ")
    return s


def strings_match_exact(gold: Any, predicted: Any) -> bool:
    """Return True if normalised gold == normalised predicted."""
    return normalize_string(gold) == normalize_string(predicted)


def strings_match_partial(gold: Any, predicted: Any) -> bool:
    """
    Return True if the normalised gold value is a substring of the predicted
    value OR the predicted value is a substring of the gold value.
    This handles minor truncation or extra context in the extracted field.
    """
    g = normalize_string(gold)
    p = normalize_string(predicted)
    if not g or not p:
        return False
    return g in p or p in g


def numeric_within_tolerance(gold: Any, predicted: Any, pct: float = 0.05) -> bool:
    """
    Return True if |predicted - gold| / gold <= pct.
    Handles string-encoded numbers.
    """
    try:
        g = float(str(gold).replace(",", "").replace("€", "").strip())
        p = float(str(predicted).replace(",", "").replace("€", "").strip())
        if g == 0:
            return p == 0
        return abs(p - g) / abs(g) <= pct
    except (TypeError, ValueError):
        return False


def token_overlap_f1(gold_str: str, pred_str: str) -> float:
    """
    Compute token-level F1 between two strings.
    Used for long text fields and treatment_type matching.
    """
    g_tokens = set(normalize_string(gold_str).split())
    p_tokens = set(normalize_string(pred_str).split())
    if not g_tokens and not p_tokens:
        return 1.0
    if not g_tokens or not p_tokens:
        return 0.0
    overlap = g_tokens & p_tokens
    prec = len(overlap) / len(p_tokens)
    rec = len(overlap) / len(g_tokens)
    return 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0


def match_receipts(
    gold_receipts: List[Dict[str, Any]],
    pred_receipts: Any,
) -> Tuple[int, int, int, int, int]:
    """
    Match predicted receipts to gold receipts by greedy treatment_type similarity.

    Returns (tp_treatment, fp_treatment, fn_treatment, within_cost_5pct, total_gold_rows).
    """
    if not isinstance(pred_receipts, list):
        pred_receipts = []

    total_gold = len(gold_receipts)
    tp_t = fp_t = fn_t = within_cost = 0

    # Build a used-mask for predicted receipts
    used_pred = [False] * len(pred_receipts)

    for g_row in gold_receipts:
        g_type = normalize_string(g_row.get("treatment_type", ""))
        g_cost = g_row.get("total_cost")
        best_score = 0.0
        best_idx = -1

        for j, p_row in enumerate(pred_receipts):
            if used_pred[j]:
                continue
            if not isinstance(p_row, dict):
                continue
            p_type = normalize_string(p_row.get("treatment_type", ""))
            score = token_overlap_f1(g_type, p_type)
            if score > best_score:
                best_score = score
                best_idx = j

        if best_idx >= 0 and best_score >= 0.5:
            used_pred[best_idx] = True
            tp_t += 1
            p_cost = pred_receipts[best_idx].get("total_cost")
            if numeric_within_tolerance(g_cost, p_cost):
                within_cost += 1
        else:
            fn_t += 1

    # Unmatched predictions are false positives
    fp_t = sum(1 for u in used_pred if not u)

    return tp_t, fp_t, fn_t, within_cost, total_gold


def _invoke_bedrock_with_retry(
    subject: str,
    email_body: str,
    text_chunks: List[str],
    email_id: str,
) -> Tuple[Dict[str, Any], float, bool]:
    """
    Call _extract_via_bedrock with one retry on throttle/connection errors.

    Returns (extracted_fields, confidence, was_called).
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            fields, conf, called = _extract_via_bedrock(
                subject=subject,
                email_body=email_body,
                text_chunks=text_chunks,
                email_id=email_id,
            )
            return fields, conf, called
        except Exception as exc:
            err_msg = str(exc).lower()
            if attempt < MAX_RETRIES and (
                "throttl" in err_msg
                or "too many requests" in err_msg
                or "connection" in err_msg
            ):
                logger.warning(
                    "Bedrock throttle on %s (attempt %d). Retrying in %.0fs.",
                    email_id, attempt + 1, RETRY_SLEEP_S
                )
                time.sleep(RETRY_SLEEP_S)
            else:
                raise


# ── Dataset loading ────────────────────────────────────────────────────────────

def load_dataset(path: str, limit: Optional[int] = None) -> List[GoldRecord]:
    """
    Load gold records from a JSONL file.

    Each line must be a valid JSON object matching the claim_form_gold_dataset schema.
    """
    records: List[GoldRecord] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                records.append(GoldRecord(
                    test_id=obj["test_id"],
                    scenario=obj.get("scenario", "unknown"),
                    email=obj["email"],
                    pdf_text=obj["pdf_text"],
                    gold_fields=obj["gold_fields"],
                    expected_intent=obj.get("expected_intent", "claim_submission"),
                    expected_route=obj.get("expected_route", "claims_team"),
                ))
            except (KeyError, json.JSONDecodeError) as exc:
                logger.error("Line %d parse error: %s", lineno, exc)
    if limit:
        records = records[:limit]
    return records


# ── Per-record evaluation ──────────────────────────────────────────────────────

def evaluate_record(
    record: GoldRecord,
    string_results: Dict[str, FieldResult],
    bool_results: Dict[str, FieldResult],
    numeric_results: Dict[str, NumericResult],
    receipts_result: ReceiptsResult,
    dependants_result: DependantsResult,
) -> RunRecord:
    """
    Run extraction for one gold record and update all metric accumulators in-place.

    Returns a RunRecord with per-record summary information.
    """
    email = record.email
    text_chunk = f"[PDF: claim_form.pdf]\n{record.pdf_text}"

    t0 = time.monotonic()
    error_msg: Optional[str] = None
    fields: Dict[str, Any] = {}
    confidence: float = 0.5
    bedrock_called: bool = False

    try:
        fields, confidence, bedrock_called = _invoke_bedrock_with_retry(
            subject=email.get("subject", ""),
            email_body=email.get("body_text", ""),
            text_chunks=[text_chunk],
            email_id=record.test_id,
        )
    except Exception as exc:
        error_msg = str(exc)
        logger.error("Extraction failed for %s: %s", record.test_id, exc)

    latency_ms = int((time.monotonic() - t0) * 1000)
    gold = record.gold_fields

    # ── String fields ──────────────────────────────────────────────────────────
    for fname in STRING_FIELDS:
        res = string_results[fname]
        g_val = gold.get(fname)
        p_val = fields.get(fname)

        # Normalise "NOT COMPLETED" placeholder to None
        if isinstance(p_val, str) and "not completed" in p_val.lower():
            p_val = None

        if g_val is not None:
            res.total_gold_present += 1
            if p_val is not None:
                if strings_match_exact(g_val, p_val):
                    res.tp_exact += 1
                    res.tp_partial += 1  # exact implies partial
                elif strings_match_partial(g_val, p_val):
                    res.tp_partial += 1
                    res.fn += 1  # not an exact match
                else:
                    res.fn += 1
            else:
                res.fn += 1
        else:
            res.total_gold_absent += 1
            if p_val is not None:
                res.fp += 1
            else:
                res.tn += 1

    # ── Boolean fields ─────────────────────────────────────────────────────────
    for fname in BOOL_FIELDS:
        res = bool_results[fname]
        g_val = gold.get(fname)
        p_val = fields.get(fname)

        if g_val is not None:
            res.total_gold_present += 1
            if p_val is not None and bool(p_val) == bool(g_val):
                res.tp_exact += 1
                res.tp_partial += 1
            else:
                res.fn += 1
        else:
            res.total_gold_absent += 1
            if p_val is not None:
                res.fp += 1
            else:
                res.tn += 1

    # ── Numeric fields ─────────────────────────────────────────────────────────
    for fname in NUMERIC_FIELDS:
        res = numeric_results[fname]
        g_val = gold.get(fname)
        p_val = fields.get(fname)

        if g_val is not None:
            res.total_gold_present += 1
            if p_val is not None:
                try:
                    g_f = float(str(g_val).replace(",", ""))
                    p_f = float(str(p_val).replace(",", ""))
                    res.mae_sum += abs(p_f - g_f)
                    if numeric_within_tolerance(g_f, p_f):
                        res.within_5pct += 1
                except (TypeError, ValueError):
                    pass
        else:
            if p_val is not None:
                res.fp += 1
            else:
                res.tn += 1

    # ── Receipts array ─────────────────────────────────────────────────────────
    gold_receipts: List[Dict] = gold.get("receipts") or []
    pred_receipts = fields.get("receipts")
    if gold_receipts or isinstance(pred_receipts, list):
        tp_t, fp_t, fn_t, wc, total_gold = match_receipts(gold_receipts, pred_receipts)
        receipts_result.tp_treatment += tp_t
        receipts_result.fp_treatment += fp_t
        receipts_result.fn_treatment += fn_t
        receipts_result.within_cost_5pct += wc
        receipts_result.total_receipt_rows_gold += total_gold

    # ── Dependants array ───────────────────────────────────────────────────────
    gold_deps: List[Dict] = gold.get("dependants") or []
    pred_deps = fields.get("dependants")
    if not isinstance(pred_deps, list):
        pred_deps = []

    if gold_deps:
        dependants_result.gold_present_count += 1
        if pred_deps:
            dependants_result.predicted_present_count += 1
        for g_dep in gold_deps:
            g_name = normalize_string(g_dep.get("name", ""))
            # Try to find a matching prediction by name token overlap
            matched = False
            for p_dep in pred_deps:
                if not isinstance(p_dep, dict):
                    continue
                p_name = normalize_string(p_dep.get("name", ""))
                if token_overlap_f1(g_name, p_name) >= 0.5:
                    matched = True
                    dependants_result.name_tp += 1
                    break
            if not matched:
                dependants_result.name_fn += 1
        # Count unmatched predictions as FP
        for p_dep in pred_deps:
            if not isinstance(p_dep, dict):
                continue
            p_name = normalize_string(p_dep.get("name", ""))
            found = any(
                token_overlap_f1(normalize_string(g.get("name", "")), p_name) >= 0.5
                for g in gold_deps
            )
            if not found:
                dependants_result.name_fp += 1

    return RunRecord(
        test_id=record.test_id,
        scenario=record.scenario,
        latency_ms=latency_ms,
        bedrock_called=bedrock_called,
        extraction_confidence=confidence,
        error=error_msg,
    )


# ── Reporting ──────────────────────────────────────────────────────────────────

def compute_overall_score(
    string_results: Dict[str, FieldResult],
    bool_results: Dict[str, FieldResult],
    numeric_results: Dict[str, NumericResult],
    receipts_result: ReceiptsResult,
    dependants_result: DependantsResult,
) -> float:
    """
    Compute a single weighted overall extraction score in [0, 1].

    Weights:
      - Core identity fields (surname, forenames, membership_no, dob): 30%
      - Payment fields (account_*, bank_*):                             20%
      - Receipts (treatment F1 + cost accuracy):                        20%
      - Specialist sections (MRI, accident, dental):                    20%
      - Dependants + bool fields:                                       10%
    """
    def f1_of(res: FieldResult) -> float:
        return res.f1_partial  # use partial match for overall score

    # Core identity
    core_fields = ["surname", "forenames", "membership_no", "date_of_birth"]
    core_score = sum(f1_of(string_results[f]) for f in core_fields) / len(core_fields)

    # Payment fields
    pay_fields = ["account_holder_name", "account_number", "bank_sort_code", "bank_name_address"]
    pay_score = sum(f1_of(string_results[f]) for f in pay_fields) / len(pay_fields)

    # Receipts
    rec_score = (receipts_result.treatment_f1 + receipts_result.cost_accuracy) / 2

    # Specialist sections
    spec_fields = [
        "mri_date", "mri_centre", "mri_procedure", "mri_referring_gp",
        "accident_date", "accident_description",
        "dental_injury_date", "dental_injury_description",
    ]
    spec_present = [f for f in spec_fields if string_results[f].total_gold_present > 0]
    if spec_present:
        spec_score_str = sum(f1_of(string_results[f]) for f in spec_present) / len(spec_present)
    else:
        spec_score_str = 1.0
    dental_cost_res = numeric_results["dental_cost"]
    spec_score = (spec_score_str + dental_cost_res.accuracy) / 2

    # Dependants + booleans
    dep_score = dependants_result.detection_recall
    bool_scores = [f1_of(bool_results[f]) for f in BOOL_FIELDS
                   if bool_results[f].total_gold_present > 0]
    bool_avg = sum(bool_scores) / len(bool_scores) if bool_scores else 1.0
    dep_bool_score = (dep_score + bool_avg) / 2

    overall = (
        0.30 * core_score
        + 0.20 * pay_score
        + 0.20 * rec_score
        + 0.20 * spec_score
        + 0.10 * dep_bool_score
    )
    return round(overall, 4)


SEP = "=" * 70
SUB_SEP = "-" * 70


def print_report(
    run_records: List[RunRecord],
    string_results: Dict[str, FieldResult],
    bool_results: Dict[str, FieldResult],
    numeric_results: Dict[str, NumericResult],
    receipts_result: ReceiptsResult,
    dependants_result: DependantsResult,
    overall_score: float,
) -> None:
    """Print a structured, human-readable evaluation report to stdout."""

    total = len(run_records)
    successful = sum(1 for r in run_records if r.error is None)
    avg_conf = (
        sum(r.extraction_confidence for r in run_records if r.error is None) / successful
        if successful else 0.0
    )
    avg_latency = (
        sum(r.latency_ms for r in run_records) / total if total else 0
    )

    print()
    print(SEP)
    print("  Claim Form Extraction Evaluation — InsureMail AI")
    print(SEP)
    print(f"  Total records   : {total}")
    print(f"  Successful      : {successful}")
    print(f"  Failed          : {total - successful}")
    print(f"  Avg confidence  : {avg_conf:.3f}")
    print(f"  Avg latency     : {avg_latency:.0f} ms")
    print()

    # ── String field results ───────────────────────────────────────────────────
    print(SUB_SEP)
    print("  String Field Results (Exact Match | Partial Match)")
    print(SUB_SEP)
    header = f"  {'Field':<30}  {'GP':>6}  {'Prec(E)':>8}  {'Rec(E)':>7}  {'F1(E)':>6}  {'F1(P)':>6}  {'Null%':>6}"
    print(header)
    print("  " + "-" * 66)
    for fname in STRING_FIELDS:
        res = string_results[fname]
        gp = res.total_gold_present
        print(
            f"  {fname:<30}  {gp:>6}  "
            f"{res.precision_exact:>8.3f}  {res.recall_exact:>7.3f}  "
            f"{res.f1_exact:>6.3f}  {res.f1_partial:>6.3f}  "
            f"{res.null_accuracy:>6.3f}"
        )

    print()
    print(SUB_SEP)
    print("  Boolean Field Results")
    print(SUB_SEP)
    print(f"  {'Field':<30}  {'GP':>6}  {'Prec':>8}  {'Rec':>7}  {'F1':>6}  {'Null%':>6}")
    print("  " + "-" * 60)
    for fname in BOOL_FIELDS:
        res = bool_results[fname]
        print(
            f"  {fname:<30}  {res.total_gold_present:>6}  "
            f"{res.precision_exact:>8.3f}  {res.recall_exact:>7.3f}  "
            f"{res.f1_exact:>6.3f}  {res.null_accuracy:>6.3f}"
        )

    print()
    print(SUB_SEP)
    print("  Numeric Field Results (5% tolerance)")
    print(SUB_SEP)
    print(f"  {'Field':<30}  {'GP':>6}  {'Accuracy':>9}  {'MAE':>8}")
    print("  " + "-" * 55)
    for fname in NUMERIC_FIELDS:
        res = numeric_results[fname]
        print(
            f"  {fname:<30}  {res.total_gold_present:>6}  "
            f"{res.accuracy:>9.3f}  {res.mae:>8.2f}"
        )

    print()
    print(SUB_SEP)
    print("  Receipts Array Results")
    print(SUB_SEP)
    print(f"  Gold receipt rows    : {receipts_result.total_receipt_rows_gold}")
    print(f"  Treatment type F1    : {receipts_result.treatment_f1:.3f}")
    print(f"  Cost within 5% (acc) : {receipts_result.cost_accuracy:.3f}")

    print()
    print(SUB_SEP)
    print("  Dependants Array Results")
    print(SUB_SEP)
    print(f"  Records with dependants : {dependants_result.gold_present_count}")
    print(f"  Detection recall        : {dependants_result.detection_recall:.3f}")
    print(f"  Name match F1           : {dependants_result.name_f1:.3f}")

    # ── Scenario breakdown ─────────────────────────────────────────────────────
    print()
    print(SUB_SEP)
    print("  Scenario Breakdown")
    print(SUB_SEP)
    print(f"  {'Scenario':<30}  {'N':>4}  {'Errors':>7}  {'Avg Conf':>9}")
    print("  " + "-" * 55)

    from collections import defaultdict
    by_scenario: Dict[str, List[RunRecord]] = defaultdict(list)
    for r in run_records:
        by_scenario[r.scenario].append(r)

    for scenario_key, label in SCENARIO_LABELS.items():
        recs = by_scenario.get(scenario_key, [])
        n = len(recs)
        errors = sum(1 for r in recs if r.error is not None)
        avg_c = sum(r.extraction_confidence for r in recs) / n if n else 0.0
        print(f"  {label:<30}  {n:>4}  {errors:>7}  {avg_c:>9.3f}")

    # ── Errors detail ──────────────────────────────────────────────────────────
    error_records = [r for r in run_records if r.error]
    if error_records:
        print()
        print(SUB_SEP)
        print("  Extraction Errors")
        print(SUB_SEP)
        for r in error_records:
            print(f"  {r.test_id} ({r.scenario}): {r.error[:120]}")

    # ── Overall score ──────────────────────────────────────────────────────────
    print()
    print(SEP)
    print(f"  Overall Extraction Score : {overall_score:.4f} / 1.0000")
    print(SEP)
    print()


# ── JSON summary builder ───────────────────────────────────────────────────────

def build_summary(
    run_records: List[RunRecord],
    string_results: Dict[str, FieldResult],
    bool_results: Dict[str, FieldResult],
    numeric_results: Dict[str, NumericResult],
    receipts_result: ReceiptsResult,
    dependants_result: DependantsResult,
    overall_score: float,
    dataset_path: str,
) -> Dict[str, Any]:
    """Construct a dashboard-ready JSON summary dictionary."""
    total = len(run_records)
    successful = [r for r in run_records if r.error is None]

    string_field_summary = {}
    for fname, res in string_results.items():
        string_field_summary[fname] = {
            "gold_present": res.total_gold_present,
            "gold_absent": res.total_gold_absent,
            "precision_exact": round(res.precision_exact, 4),
            "recall_exact": round(res.recall_exact, 4),
            "f1_exact": round(res.f1_exact, 4),
            "f1_partial": round(res.f1_partial, 4),
            "null_accuracy": round(res.null_accuracy, 4),
        }
    for fname, res in bool_results.items():
        string_field_summary[fname] = {
            "gold_present": res.total_gold_present,
            "gold_absent": res.total_gold_absent,
            "precision": round(res.precision_exact, 4),
            "recall": round(res.recall_exact, 4),
            "f1": round(res.f1_exact, 4),
            "null_accuracy": round(res.null_accuracy, 4),
        }

    numeric_field_summary = {}
    for fname, res in numeric_results.items():
        numeric_field_summary[fname] = {
            "gold_present": res.total_gold_present,
            "accuracy_within_5pct": round(res.accuracy, 4),
            "mae": round(res.mae, 2),
        }

    from collections import defaultdict
    scenario_breakdown: Dict[str, Any] = {}
    by_scenario: Dict[str, List[RunRecord]] = defaultdict(list)
    for r in run_records:
        by_scenario[r.scenario].append(r)
    for sc, recs in by_scenario.items():
        n = len(recs)
        errs = sum(1 for r in recs if r.error)
        avg_c = sum(r.extraction_confidence for r in recs) / n if n else 0.0
        avg_l = sum(r.latency_ms for r in recs) / n if n else 0.0
        scenario_breakdown[sc] = {
            "n": n,
            "errors": errs,
            "avg_confidence": round(avg_c, 3),
            "avg_latency_ms": round(avg_l, 0),
        }

    return {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_path": dataset_path,
        "model_versions": {
            "entity_extractor": os.environ.get("ENTITY_MODEL_ID", "mistral.mistral-7b-instruct-v0:2"),
            "aws_region": os.environ.get("AWS_REGION", "us-east-1"),
        },
        "run_summary": {
            "total_records": total,
            "successful": len(successful),
            "failed": total - len(successful),
            "avg_confidence": round(
                sum(r.extraction_confidence for r in successful) / len(successful), 4
            ) if successful else 0.0,
            "avg_latency_ms": round(
                sum(r.latency_ms for r in run_records) / total, 1
            ) if total else 0.0,
        },
        "overall_score": overall_score,
        "field_results": string_field_summary,
        "numeric_field_results": numeric_field_summary,
        "receipts_results": {
            "total_gold_rows": receipts_result.total_receipt_rows_gold,
            "treatment_type_f1": round(receipts_result.treatment_f1, 4),
            "cost_within_5pct_accuracy": round(receipts_result.cost_accuracy, 4),
        },
        "dependants_results": {
            "records_with_dependants": dependants_result.gold_present_count,
            "detection_recall": round(dependants_result.detection_recall, 4),
            "name_match_f1": round(dependants_result.name_f1, 4),
        },
        "scenario_breakdown": scenario_breakdown,
        "record_details": [
            {
                "test_id": r.test_id,
                "scenario": r.scenario,
                "latency_ms": r.latency_ms,
                "bedrock_called": r.bedrock_called,
                "extraction_confidence": round(r.extraction_confidence, 4),
                "error": r.error,
            }
            for r in run_records
        ],
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        description="Evaluate Laya Healthcare Out-patient Claim Form extraction pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help="Path to JSONL gold dataset file.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate only the first N records.",
    )
    p.add_argument(
        "--output",
        default=None,
        help=(
            "Path for JSON output report. "
            "Defaults to results/claim_extraction_eval_<timestamp>.json."
        ),
    )
    return p.parse_args()


def main() -> None:
    """Entry point for the claim extraction evaluation script."""
    args = parse_args()

    if not _IMPORT_OK:
        print(
            "ERROR: Could not import _extract_via_bedrock from lambda/email_parser/lambda_function.py.\n"
            "       Ensure AWS credentials are configured and ENTITY_MODEL_ID is accessible.\n"
            "       Run: export AWS_DEFAULT_REGION=us-east-1",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Load dataset ───────────────────────────────────────────────────────────
    print(f"\nLoading dataset: {args.dataset}")
    records = load_dataset(args.dataset, limit=args.limit)
    if not records:
        print("No records loaded. Check --dataset path.", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(records)} records.")

    # ── Initialise accumulators ────────────────────────────────────────────────
    string_results: Dict[str, FieldResult] = {f: FieldResult(f) for f in STRING_FIELDS}
    bool_results: Dict[str, FieldResult] = {f: FieldResult(f) for f in BOOL_FIELDS}
    numeric_results: Dict[str, NumericResult] = {f: NumericResult(f) for f in NUMERIC_FIELDS}
    receipts_result = ReceiptsResult()
    dependants_result = DependantsResult()
    run_records: List[RunRecord] = []

    # ── Evaluate each record ───────────────────────────────────────────────────
    print(f"Running extraction on {len(records)} records...\n")
    for i, record in enumerate(records, 1):
        print(f"  [{i:>2}/{len(records)}] {record.test_id} ({record.scenario})", end="", flush=True)
        run_rec = evaluate_record(
            record,
            string_results,
            bool_results,
            numeric_results,
            receipts_result,
            dependants_result,
        )
        run_records.append(run_rec)
        status = "OK" if run_rec.error is None else "ERR"
        print(
            f"  {status}  conf={run_rec.extraction_confidence:.3f}  "
            f"latency={run_rec.latency_ms}ms"
        )

    # ── Compute overall score ──────────────────────────────────────────────────
    overall_score = compute_overall_score(
        string_results, bool_results, numeric_results, receipts_result, dependants_result
    )

    # ── Print report ───────────────────────────────────────────────────────────
    print_report(
        run_records,
        string_results,
        bool_results,
        numeric_results,
        receipts_result,
        dependants_result,
        overall_score,
    )

    # ── Write JSON output ──────────────────────────────────────────────────────
    if args.output:
        out_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(DEFAULT_OUTPUT_DIR, f"claim_extraction_eval_{ts}.json")

    summary = build_summary(
        run_records,
        string_results,
        bool_results,
        numeric_results,
        receipts_result,
        dependants_result,
        overall_score,
        dataset_path=args.dataset,
    )

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print(f"Results written to: {out_path}\n")

    LOGS_BUCKET = os.environ.get("RESULTS_BUCKET", "insuremail-ai-dev-logs")
    try:
        import boto3 as _boto3
        s3 = _boto3.client("s3")
        with open(out_path, "rb") as fh:
            s3.put_object(
                Bucket=LOGS_BUCKET,
                Key="eval_reports/claim_extraction_latest.json",
                Body=fh.read(),
                ContentType="application/json",
            )
        print(f"Uploaded to s3://{LOGS_BUCKET}/eval_reports/claim_extraction_latest.json")
    except Exception as e:
        print(f"[warn] S3 upload skipped: {e}")


if __name__ == "__main__":
    main()
