"""
classify_intent_by_biobert Lambda
==================================
Classifies inbound insurance emails using a fine-tuned BioBERT model
deployed on a SageMaker endpoint.

Flow:
  1. Concatenate subject + email body into a single text string.
  2. POST to the SageMaker endpoint: {"instances": [text]}
  3. Receive softmax probabilities over the 17 intent classes.
  4. argmax → intent label → route team mapping.
  5. Return the same classification schema as classify_intent_by_llm.

Environment variables:
    SAGEMAKER_ENDPOINT_NAME  — name of the deployed BioBERT SageMaker endpoint

Input event keys (from Step Functions Parameters):
    email_id    (str) — trace ID
    email_body  (str) — plain-text email body
    subject     (str) — email subject line

Output (stored at ResultPath in Step Functions):
    statusCode          (int)
    email_id            (str)
    classification      (dict)
        customer_intent       (str) — one of the 17 valid intents
        secondary_intent      (str) — always "" (BioBERT is single-label)
        business_line         (str) — always "health_insurance"
        urgency               (str) — "low" | "medium" | "high"
        sentiment             (str) — "neutral" (BioBERT does not predict sentiment)
        gold_route_team       (str) — mapped from customer_intent
        gold_priority         (str) — "normal" | "high" | "urgent"
        requires_human_review (bool)
    confidence          (float) — softmax probability of the top intent
    model               (str)   — "biobert"
"""
import json
import logging
import os
from typing import Any, Dict, List, Tuple

import boto3
from botocore.exceptions import ClientError

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── AWS clients ───────────────────────────────────────────────────────────────
sagemaker_runtime = boto3.client("sagemaker-runtime")

# ── Environment ───────────────────────────────────────────────────────────────
SAGEMAKER_ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "")

# ── Intent label mapping ──────────────────────────────────────────────────────
# 17 labels in alphabetical order — must match the order used during BioBERT training.
BIOBERT_LABELS: List[str] = [
    "broker_query",
    "cancellation_request",
    "claim_reimbursement_query",
    "claim_status",
    "claim_submission",
    "complaint",
    "coverage_query",
    "dependent_addition",
    "document_followup",
    "enrollment_new_policy",
    "hospital_network_query",
    "id_verification",
    "other",
    "payment_issue",
    "policy_change",
    "pre_authorisation",
    "renewal_query",
]

INTENT_TO_ROUTE: Dict[str, str] = {
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


# ── Lambda handler ─────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Classify a single email using the BioBERT SageMaker endpoint.
    Returns a classification dict compatible with classify_intent_by_llm.
    """
    email_id   = event.get("email_id", "")
    email_body = event.get("email_body") or event.get("body_text", "")
    subject    = event.get("subject", "")

    logger.info(json.dumps({
        "trace_id": email_id,
        "step":     "classify_intent_by_biobert",
        "endpoint": SAGEMAKER_ENDPOINT_NAME,
    }))

    if not email_body:
        raise ValueError("Missing email_body in event")
    if not SAGEMAKER_ENDPOINT_NAME:
        raise ValueError("SAGEMAKER_ENDPOINT_NAME environment variable is not set")

    classification, confidence = _classify(email_id, subject, email_body)

    logger.info(json.dumps({
        "trace_id":   email_id,
        "step":       "classify_intent_by_biobert",
        "intent":     classification["customer_intent"],
        "route":      classification["gold_route_team"],
        "confidence": confidence,
    }))

    return {
        "statusCode":     200,
        "email_id":       email_id,
        "classification": classification,
        "confidence":     confidence,
        "model":          "biobert",
    }


# ── Classification ─────────────────────────────────────────────────────────────

def _classify(
    email_id: str, subject: str, email_body: str
) -> Tuple[Dict[str, Any], float]:
    """
    Send text to the SageMaker BioBERT endpoint and decode the result.
    Returns (classification_dict, confidence_score).
    """
    # Combine subject + body for richer context (max 512 tokens handled by model)
    text = f"{subject} {email_body}".strip() if subject else email_body

    probabilities = _invoke_endpoint(email_id, text)
    intent, confidence = _decode_predictions(probabilities)

    route = INTENT_TO_ROUTE.get(intent, "general_support_team")

    # Apply urgency heuristic: high-priority intents get "high" urgency
    high_urgency_intents = {"complaint", "pre_authorisation", "claim_submission"}
    urgency   = "high"   if intent in high_urgency_intents else "medium"
    priority  = "urgent" if intent in {"complaint", "pre_authorisation"} else "normal"
    requires_human_review = intent in {"complaint", "pre_authorisation"} or priority == "urgent"

    return {
        "customer_intent":       intent,
        "secondary_intent":      "",
        "business_line":         "health_insurance",
        "urgency":               urgency,
        "sentiment":             "neutral",
        "gold_route_team":       route,
        "gold_priority":         priority,
        "requires_human_review": requires_human_review,
    }, confidence


def _invoke_endpoint(email_id: str, text: str) -> List[float]:
    """
    POST text to the SageMaker endpoint.
    Returns the list of per-class probabilities (softmax output).
    Raises on any SageMaker error.
    """
    payload = json.dumps({"instances": [text]})

    try:
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName = SAGEMAKER_ENDPOINT_NAME,
            ContentType  = "application/json",
            Accept       = "application/json",
            Body         = payload.encode("utf-8"),
        )
        raw = json.loads(response["Body"].read().decode("utf-8"))

    except sagemaker_runtime.exceptions.ModelNotReadyException:
        logger.error(json.dumps({
            "trace_id": email_id,
            "error":    "sagemaker_endpoint_not_ready",
            "endpoint": SAGEMAKER_ENDPOINT_NAME,
        }))
        raise
    except ClientError as exc:
        logger.error(json.dumps({
            "trace_id": email_id,
            "error":    "sagemaker_client_error",
            "message":  exc.response["Error"]["Message"],
        }))
        raise

    # HuggingFace DLC wraps output as [json_string, "application/json"]
    if isinstance(raw, list) and len(raw) == 2 and isinstance(raw[0], str):
        raw = json.loads(raw[0])

    predictions = raw.get("predictions", raw) if isinstance(raw, dict) else raw

    # predictions shape: [[p0, p1, ..., p16]]  — one row per input instance
    if isinstance(predictions, list) and predictions and isinstance(predictions[0], list):
        return predictions[0]

    # Flat list (single instance, some model configs)
    if isinstance(predictions, list) and predictions and isinstance(predictions[0], (int, float)):
        return predictions

    raise ValueError(f"Unexpected predictions format from SageMaker: {type(predictions)}")


def _decode_predictions(probabilities: List[float]) -> Tuple[str, float]:
    """
    Map softmax probability vector → (intent_label, confidence).
    Falls back to 'other' if the label count doesn't match.
    """
    if len(probabilities) != len(BIOBERT_LABELS):
        logger.warning(json.dumps({
            "warning":        "biobert_label_count_mismatch",
            "expected":       len(BIOBERT_LABELS),
            "received":       len(probabilities),
        }))
        # Best-effort: map up to the available labels
        labels = BIOBERT_LABELS[:len(probabilities)]
        if not labels:
            return "other", 0.0
    else:
        labels = BIOBERT_LABELS

    max_idx    = probabilities.index(max(probabilities))
    intent     = labels[max_idx] if max_idx < len(labels) else "other"
    confidence = round(float(probabilities[max_idx]), 4)
    return intent, confidence
