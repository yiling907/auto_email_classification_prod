"""
CRM Validation Lambda
=====================
Text-to-SQL pipeline for customer/policy lookup against DynamoDB.

Flow:
  1. Schema-aware prompt → Mistral 7B (Bedrock) → JSON query plan
     { lookup_field, lookup_value, confidence }
  2. Input sanitisation (regex whitelist per field type)
  3. Safe DynamoDB execution:
       customer_id  → GetItem  (O(1), exact PK match)
       policy_number / member_id / email → Scan + FilterExpression
  4. Policy validation: active status, coverage, renewal, intent eligibility
  5. Returns structured crm_context dict consumed by llm_response Lambda

Environment variables:
    CUSTOMERS_TABLE_NAME   — DynamoDB table name (required)
    TEXT2SQL_MODEL_ID      — Bedrock model ID for query planning
                             (default: mistral.mistral-7b-instruct-v0:2)
    AWS_REGION             — AWS region (default: us-east-1)

Input event keys (all passed through from Step Functions state):
    email_id            (str)  — trace ID
    intent              (str)  — classified intent from classify_intent Lambda
    email_body          (str)  — full email body
    extracted_entities  (dict) — entities from email_parser Lambda
        customer_id     (str, optional)
        member_id       (str, optional)
        policy_number   (str, optional)
        email           (str, optional)

Output (merged into Step Functions state):
    crm_context         (dict) — structured customer/policy data for Claude
    crm_found           (bool) — whether a matching record was located
    email_id            (str)  — pass-through
    intent              (str)  — pass-through
"""

import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

# ── Logging ───────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── AWS clients (initialised once at cold start) ──────────────────────────────

_REGION = os.environ.get("AWS_REGION", "us-east-1")
bedrock  = boto3.client("bedrock-runtime", region_name=_REGION)
dynamodb = boto3.resource("dynamodb",       region_name=_REGION)

# ── Environment ───────────────────────────────────────────────────────────────

CUSTOMERS_TABLE_NAME = os.environ.get("CUSTOMERS_TABLE_NAME", "insuremail-ai-dev-customers")
TEXT2SQL_MODEL_ID    = os.environ.get(
    "TEXT2SQL_MODEL_ID", "mistral.mistral-7b-instruct-v0:2"
)

customers_table = dynamodb.Table(CUSTOMERS_TABLE_NAME)

# ── Table schema exposed to the Text-to-SQL model ────────────────────────────
# This is the source of truth the model uses to generate its query plan.
# Only identifier fields are included — the model must not attempt to
# look up on non-indexed, free-text columns (e.g. address, full_name).

_TABLE_SCHEMA = """
Table name  : customers
Primary key : customer_id  (string, format "CUST-XXXXXX", direct GetItem)

Queryable lookup fields (use only these for WHERE-equivalent conditions):
  customer_id   — format "CUST-XXXXXX"  (preferred: O(1) GetItem)
  member_id     — format "MEM-XXXXXX"
  policy_number — format "POL-IE-XXXXXX"
  email         — customer e-mail address

Other fields in the table (returned in results, not used for lookup):
  full_name, phone, address, county, dob, plan_name,
  policy_start_date, renewal_date, member_count,
  family_status, payment_method, preferred_language
""".strip()

# ── Lookup field validation patterns ─────────────────────────────────────────
# Model output is never trusted directly — every value is matched against a
# strict regex before it touches DynamoDB.  Anything that fails validation
# causes a graceful "not found" result rather than an exception.

_FIELD_PATTERNS: Dict[str, re.Pattern] = {
    "customer_id":   re.compile(r"^CUST-\d{6}$"),
    "member_id":     re.compile(r"^MEM-\d{6}$"),
    "policy_number": re.compile(r"^POL-IE-\d{6}$"),
    "email":         re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"),
}

# Only these fields are valid lookup targets (whitelist, not blocklist).
_ALLOWED_LOOKUP_FIELDS = frozenset(_FIELD_PATTERNS.keys())

# ── Plan coverage limits (EUR, annual) ───────────────────────────────────────
# The DynamoDB table stores plan_name but not coverage limits; we derive them
# here.  Values are indicative for Laya Healthcare Ireland plans.

_PLAN_COVERAGE: Dict[str, Dict[str, Any]] = {
    "Essential Care":  {"annual_limit_eur": 50_000,  "daily_rate_eur": 100},
    "Everyday Care":   {"annual_limit_eur": 75_000,  "daily_rate_eur": 150},
    "Select Hospital": {"annual_limit_eur": 100_000, "daily_rate_eur": 200},
    "HealthWise Gold": {"annual_limit_eur": 150_000, "daily_rate_eur": 250},
    "Family Plus":     {"annual_limit_eur": 200_000, "daily_rate_eur": 300},
    "Corporate Flex":  {"annual_limit_eur": 250_000, "daily_rate_eur": 350},
}
_DEFAULT_COVERAGE = {"annual_limit_eur": None, "daily_rate_eur": None}

# ── Intent → required policy checks ──────────────────────────────────────────
# Maps each classified intent to the minimum policy state needed to handle it.

_INTENT_REQUIRES_ACTIVE = frozenset({
    "claim_submission",
    "claim_status",
    "claim_reimbursement_query",
    "pre_authorisation",
    "coverage_query",
    "payment_issue",
    "policy_change",
    "dependent_addition",
    "hospital_network_query",
})

# ── Text-to-SQL prompt ────────────────────────────────────────────────────────

_QUERY_PLAN_PROMPT = """\
You are a database query planner for an insurance company CRM system.
Your job is to read a customer's email and extract the best identifier \
to look up their record in the customers table.

{schema}

Customer email intent : {intent}
Extracted entities    : {entities_json}
Email excerpt (first 400 chars):
\"\"\"
{email_excerpt}
\"\"\"

Rules:
1. Choose EXACTLY ONE lookup field from: customer_id, member_id, policy_number, email
2. The lookup_value must appear verbatim in the email or extracted entities
3. Prefer customer_id > member_id > policy_number > email (most → least precise)
4. If no valid identifier is present, set lookup_field and lookup_value to null

Respond with ONLY valid JSON — no explanation, no markdown, no extra keys:
{{
  "lookup_field": "<field name or null>",
  "lookup_value": "<exact value or null>",
  "confidence": <float 0.0-1.0>
}}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
# Public Lambda handler
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Entry point called by Step Functions.

    Merges crm_context into the pipeline state and returns the full state
    so downstream steps receive all accumulated data.
    """
    email_id = event.get("email_id", "unknown")
    intent   = event.get("intent",   "other")

    logger.info(json.dumps({
        "trace_id": email_id,
        "step":     "crm_validation",
        "intent":   intent,
    }))

    crm_context = _run_crm_lookup(
        intent            = intent,
        email_body        = event.get("email_body", ""),
        extracted_entities= event.get("extracted_entities", {}),
        email_id          = email_id,
    )

    # Return ONLY the CRM output — Step Functions stores this at the ResultPath
    # configured in the state machine ($.crm_validation) and handles merging.
    # Do NOT return the full event here; that would cause ResultPath duplication.
    return crm_context


# ══════════════════════════════════════════════════════════════════════════════
# Step 1 — Text-to-SQL: generate query plan via Mistral 7B
# ══════════════════════════════════════════════════════════════════════════════

def _build_query_plan(
    intent:     str,
    email_body: str,
    entities:   Dict[str, Any],
) -> Dict[str, Any]:
    """
    Call Mistral 7B (via Bedrock) with a schema-aware prompt and parse the
    JSON query plan it returns.

    Returns a dict with keys: lookup_field, lookup_value, confidence,
    model_used, latency_ms, raw_model_output.

    Never raises — returns a null plan on any failure so the pipeline
    degrades gracefully.
    """
    prompt = _QUERY_PLAN_PROMPT.format(
        schema        = _TABLE_SCHEMA,
        intent        = intent,
        entities_json = json.dumps(entities, default=str),
        email_excerpt = email_body[:400].replace('"', "'"),
    )

    # Mistral instruction format: <s>[INST] … [/INST]
    body = json.dumps({
        "prompt":      f"<s>[INST] {prompt} [/INST]",
        "max_tokens":  128,
        "temperature": 0.0,   # deterministic — this is a structured extraction task
        "top_p":       1.0,
    })

    t0 = time.monotonic()
    try:
        response = bedrock.invoke_model(
            modelId     = TEXT2SQL_MODEL_ID,
            body        = body,
            contentType = "application/json",
            accept      = "application/json",
        )
        raw = json.loads(response["body"].read())
        # Mistral response shape: {"outputs": [{"text": "..."}]}
        model_text = (raw.get("outputs") or [{}])[0].get("text", "")
    except Exception as exc:
        logger.warning("text2sql model call failed: %s", exc)
        return _null_query_plan(latency_ms=int((time.monotonic() - t0) * 1000))

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Parse the JSON the model produced
    plan = _parse_model_json(model_text)
    plan.update({
        "model_used":        TEXT2SQL_MODEL_ID,
        "latency_ms":        latency_ms,
        "raw_model_output":  model_text[:200],   # truncated for logging safety
    })
    return plan


def _parse_model_json(text: str) -> Dict[str, Any]:
    """
    Extract the first JSON object from the model's text output.
    Returns a null plan on parse failure.
    """
    # Find the first '{...}' block in the model output
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not match:
        logger.warning("no JSON object found in model output")
        return {"lookup_field": None, "lookup_value": None, "confidence": 0.0}
    try:
        obj = json.loads(match.group())
        return {
            "lookup_field": obj.get("lookup_field"),
            "lookup_value": str(obj.get("lookup_value") or "").strip() or None,
            "confidence":   float(obj.get("confidence", 0.0)),
        }
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("failed to parse model JSON: %s", exc)
        return {"lookup_field": None, "lookup_value": None, "confidence": 0.0}


def _null_query_plan(latency_ms: int = 0) -> Dict[str, Any]:
    return {
        "lookup_field":     None,
        "lookup_value":     None,
        "confidence":       0.0,
        "model_used":       TEXT2SQL_MODEL_ID,
        "latency_ms":       latency_ms,
        "raw_model_output": None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 — Input sanitisation
# ══════════════════════════════════════════════════════════════════════════════

def _sanitise(field: Optional[str], value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Validate the model-produced query plan against strict regex rules.

    Returns (field, value) if both pass, or (None, None) if either fails.
    Raw user / model input never reaches DynamoDB unless it clears this gate.
    """
    if field not in _ALLOWED_LOOKUP_FIELDS:
        logger.warning("rejected lookup_field not in whitelist: %r", field)
        return None, None

    if not value:
        return None, None

    pattern = _FIELD_PATTERNS[field]
    if not pattern.match(value):
        logger.warning(
            "rejected lookup_value for field %r: %r (pattern: %s)",
            field, value, pattern.pattern,
        )
        return None, None

    return field, value


# ══════════════════════════════════════════════════════════════════════════════
# Step 3 — DynamoDB query execution
# ══════════════════════════════════════════════════════════════════════════════

def _execute_query(field: str, value: str) -> Optional[Dict[str, Any]]:
    """
    Execute a safe DynamoDB lookup.

    customer_id  → GetItem on the primary key  (O(1))
    anything else → Scan with FilterExpression  (O(n), appropriate for small tables)

    boto3's FilterExpression with Attr() automatically parameterises values
    via ExpressionAttributeValues — user-supplied strings never appear
    literally in the query expression.
    """
    try:
        if field == "customer_id":
            resp = customers_table.get_item(Key={"customer_id": value})
            return resp.get("Item")

        # Scan with a parameterised filter for other identifier fields.
        # NOTE: Do NOT use Limit here — DynamoDB Limit caps items *read*, not
        # items *matched*, so Limit=1 would miss any record not at the very
        # start of the table.  The customers table is small (~1000 rows) so a
        # full scan with FilterExpression is fast and correct.
        resp = customers_table.scan(FilterExpression=Attr(field).eq(value))
        items = resp.get("Items", [])
        return items[0] if items else None

    except ClientError as exc:
        logger.error("DynamoDB query failed: %s", exc.response["Error"])
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Step 4 — Policy validation
# ══════════════════════════════════════════════════════════════════════════════

def _derive_policy_status(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute policy lifecycle fields not stored explicitly in the table.

    Returns a dict:
        policy_status     — "active" | "expired" | "pending" | "unknown"
        policy_active     — bool
        days_to_renewal   — int (negative means overdue)
        renewal_required  — bool
    """
    today = date.today()

    try:
        start   = date.fromisoformat(record["policy_start_date"])
        renewal = date.fromisoformat(record["renewal_date"])
    except (KeyError, ValueError):
        return {
            "policy_status":    "unknown",
            "policy_active":    False,
            "days_to_renewal":  None,
            "renewal_required": True,
        }

    days_to_renewal = (renewal - today).days

    if start > today:
        status = "pending"
        active = False
    elif renewal < today:
        status = "expired"
        active = False
    else:
        status = "active"
        active = True

    return {
        "policy_status":    status,
        "policy_active":    active,
        "days_to_renewal":  days_to_renewal,
        "renewal_required": days_to_renewal < 30,   # flag if renewal within 30 days
    }


def _validate_for_intent(
    lifecycle:  Dict[str, Any],
    intent:     str,
    plan_name:  str,
) -> Dict[str, Any]:
    """
    Check whether the customer's policy state permits the requested action.

    Returns:
        eligible_for_intent   — bool
        ineligibility_reason  — str | None
    """
    if intent not in _INTENT_REQUIRES_ACTIVE:
        # Intents like renewal_query, cancellation_request, complaint etc.
        # do not require an active policy.
        return {"eligible_for_intent": True, "ineligibility_reason": None}

    if not lifecycle["policy_active"]:
        status = lifecycle["policy_status"]
        reason = (
            f"Policy is {status}. "
            + (
                "Please renew before submitting a claim or query."
                if status == "expired"
                else f"Policy starts on {lifecycle.get('policy_start_date', 'unknown date')}."
            )
        )
        return {"eligible_for_intent": False, "ineligibility_reason": reason}

    return {"eligible_for_intent": True, "ineligibility_reason": None}


# ══════════════════════════════════════════════════════════════════════════════
# Step 5 — PII redaction for output
# ══════════════════════════════════════════════════════════════════════════════

def _redact_pii(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of the DynamoDB record with PII fields masked.
    The masked record is safe to include in logs and CloudWatch.
    The full record is never logged; only the structured crm_context is returned.
    """
    out = dict(record)

    # Mask email: keep domain for debugging
    if "email" in out and out["email"]:
        parts = str(out["email"]).split("@")
        out["email"] = f"***@{parts[1]}" if len(parts) == 2 else "***"

    # Mask phone: keep last 3 digits
    if "phone" in out and out["phone"]:
        p = str(out["phone"])
        out["phone"] = f"***{p[-3:]}" if len(p) > 3 else "***"

    # Mask date of birth
    if "dob" in out:
        out["dob"] = "[REDACTED]"

    return out


# ══════════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════════

def _run_crm_lookup(
    intent:             str,
    email_body:         str,
    extracted_entities: Dict[str, Any],
    email_id:           str,
) -> Dict[str, Any]:
    """
    Full CRM lookup pipeline.  Returns a structured crm_context dict.
    Never raises — all failures produce a crm_found=False result.
    """
    # ── Short-circuit: check extracted_entities first ─────────────────────────
    # If the email parser already found a clean identifier, prefer it over
    # the model — it's faster and avoids a Bedrock call.
    field, value = _try_entities_shortcut(extracted_entities)
    shortcut_used = field is not None

    # ── Text-to-SQL model call (only if no entity shortcut) ───────────────────
    if not shortcut_used:
        query_plan = _build_query_plan(intent, email_body, extracted_entities)
        field, value = _sanitise(query_plan["lookup_field"], query_plan["lookup_value"])
    else:
        query_plan = {
            "model_used":       "entity_shortcut",
            "latency_ms":       0,
            "confidence":       1.0,
            "raw_model_output": None,
            "lookup_field":     field,
            "lookup_value":     value,
        }

    logger.info(json.dumps({
        "trace_id":     email_id,
        "lookup_field": field,
        "shortcut":     shortcut_used,
        "model":        query_plan.get("model_used"),
    }))

    # ── No usable identifier ───────────────────────────────────────────────────
    if not field or not value:
        return _not_found_context(
            intent     = intent,
            query_plan = query_plan,
            reason     = "No valid customer identifier found in email or entities.",
        )

    # ── DynamoDB lookup ────────────────────────────────────────────────────────
    record = _execute_query(field, value)

    if record is None:
        return _not_found_context(
            intent     = intent,
            query_plan = query_plan,
            reason     = f"No customer found for {field}={value!r}.",
        )

    # ── Policy validation ──────────────────────────────────────────────────────
    lifecycle  = _derive_policy_status(record)
    coverage   = _PLAN_COVERAGE.get(record.get("plan_name", ""), _DEFAULT_COVERAGE)
    eligibility= _validate_for_intent(lifecycle, intent, record.get("plan_name", ""))

    # ── Build structured output (PII-safe) ────────────────────────────────────
    safe = _redact_pii(record)

    crm_context: Dict[str, Any] = {
        "crm_found": True,

        # Customer section (PII-redacted)
        "customer": {
            "customer_id":        safe.get("customer_id"),
            "member_id":          safe.get("member_id"),
            "full_name":          safe.get("full_name"),
            "email":              safe.get("email"),
            "phone":              safe.get("phone"),
            "county":             safe.get("county"),
            "address":            safe.get("address"),
            "preferred_language": safe.get("preferred_language", "en"),
            "family_status":      safe.get("family_status"),
            "member_count":       _to_int(safe.get("member_count")),
        },

        # Policy section
        "policy": {
            "policy_number":    safe.get("policy_number"),
            "plan_name":        safe.get("plan_name"),
            "policy_status":    lifecycle["policy_status"],
            "policy_active":    lifecycle["policy_active"],
            "policy_start_date":safe.get("policy_start_date"),
            "renewal_date":     safe.get("renewal_date"),
            "days_to_renewal":  lifecycle["days_to_renewal"],
            "renewal_required": lifecycle["renewal_required"],
            "payment_method":   safe.get("payment_method"),
            "currency":         "EUR",
            **coverage,
        },

        # Validation section
        "validation": {
            "intent":               intent,
            "policy_exists":        True,
            "eligible_for_intent":  eligibility["eligible_for_intent"],
            "ineligibility_reason": eligibility["ineligibility_reason"],
        },

        # Query audit trail (safe to log)
        "query_audit": {
            "model_used":        query_plan.get("model_used"),
            "lookup_field":      field,
            "lookup_value":      value,
            "model_confidence":  query_plan.get("confidence"),
            "latency_ms":        query_plan.get("latency_ms"),
            "shortcut_used":     shortcut_used,
        },
    }

    logger.info(json.dumps({
        "trace_id":       email_id,
        "step":           "crm_validation",
        "crm_found":      True,
        "policy_status":  lifecycle["policy_status"],
        "eligible":       eligibility["eligible_for_intent"],
    }))

    return crm_context


# ── Helpers ───────────────────────────────────────────────────────────────────

def _try_entities_shortcut(entities: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    If the email parser already extracted a clean identifier, use it directly
    instead of calling the Text-to-SQL model.  Preference order mirrors the
    DynamoDB efficiency: customer_id (PK) > member_id > policy_number > email.
    """
    for field in ("customer_id", "member_id", "policy_number", "email"):
        value = str(entities.get(field) or "").strip()
        if value:
            clean_field, clean_value = _sanitise(field, value)
            if clean_field:
                return clean_field, clean_value
    return None, None


def _not_found_context(
    intent:     str,
    query_plan: Dict[str, Any],
    reason:     str,
) -> Dict[str, Any]:
    """Return a structured 'not found' CRM context — never raises."""
    return {
        "crm_found":  False,
        "customer":   None,
        "policy":     None,
        "validation": {
            "intent":               intent,
            "policy_exists":        False,
            "eligible_for_intent":  False,
            "ineligibility_reason": reason,
        },
        "query_audit": {
            "model_used":       query_plan.get("model_used"),
            "lookup_field":     query_plan.get("lookup_field"),
            "lookup_value":     query_plan.get("lookup_value"),
            "model_confidence": query_plan.get("confidence"),
            "latency_ms":       query_plan.get("latency_ms"),
            "shortcut_used":    False,
        },
    }


def _to_int(value: Any) -> Optional[int]:
    """Safely convert DynamoDB string/Decimal member_count to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
