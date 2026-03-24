"""
classify_intent_by_biobert Lambda
==================================
Classifies inbound insurance emails using a fine-tuned MultiLabelBioBERT model
deployed on a SageMaker Serverless endpoint.

The endpoint (sagemaker/inference.py) returns:
    {
      "predictions": [{
        "intent":        str,           # top intent or "other" if ambiguous
        "score":         float,         # top class probability
        "multi_intents": [str, ...],    # labels above threshold (≥ 0.3)
        "route_team":    str,           # mapped from intent
        "all_scores":    {label: float} # per-class sigmoid probabilities
      }]
    }

Environment variables:
    SAGEMAKER_ENDPOINT_NAME  — name of the deployed BioBERT SageMaker endpoint

Input event keys (from Step Functions):
    email_id    (str) — trace ID
    email_body  (str) — plain-text email body  (also accepts body_text)
    subject     (str) — email subject line

Output:
    statusCode          (int)
    email_id            (str)
    classification      (dict) — same schema as classify_intent_by_llm
    confidence          (float)
    model               (str)  — "biobert"
"""
import json
import logging
import os
from typing import Any, Dict, Tuple

import boto3
from botocore.exceptions import ClientError

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── AWS clients ───────────────────────────────────────────────────────────────
sagemaker_runtime = boto3.client("sagemaker-runtime")

# ── Environment ───────────────────────────────────────────────────────────────
SAGEMAKER_ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "")

# ── Urgency / priority heuristics ────────────────────────────────────────────
_HIGH_URGENCY  = {"complaint", "pre_authorisation", "claim_submission"}
_URGENT_PRIO   = {"complaint", "pre_authorisation"}


# ── Lambda handler ─────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
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
    text = f"{subject} {email_body}".strip() if subject else email_body
    prediction = _invoke_endpoint(email_id, text)

    intent     = prediction.get("intent", "other")
    confidence = round(float(prediction.get("score", 0.0)), 4)
    route      = prediction.get("route_team") or "general_support_team"

    urgency  = "high"   if intent in _HIGH_URGENCY else "medium"
    priority = "urgent" if intent in _URGENT_PRIO  else "normal"
    requires_human_review = intent in _URGENT_PRIO or priority == "urgent"

    return {
        "customer_intent":       intent,
        "secondary_intent":      "",
        "business_line":         "health_insurance",
        "urgency":               urgency,
        "sentiment":             "neutral",
        "gold_route_team":       route,
        "gold_priority":         priority,
        "requires_human_review": requires_human_review,
        "all_scores":            prediction.get("all_scores", {}),
        "multi_intents":         prediction.get("multi_intents", [intent]),
    }, confidence


# ── Endpoint invocation ────────────────────────────────────────────────────────

def _invoke_endpoint(email_id: str, text: str) -> Dict[str, Any]:
    """
    POST text to the SageMaker MultiLabelBioBERT endpoint.
    Returns the first prediction dict from {"predictions": [...]}.
    Raises on SageMaker errors.
    """
    payload = json.dumps({"text": text[:2000]})   # truncate to 2000 chars

    try:
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType="application/json",
            Accept="application/json",
            Body=payload.encode("utf-8"),
        )
        raw = json.loads(response["Body"].read().decode("utf-8"))

    except ClientError as exc:
        logger.error(json.dumps({
            "trace_id": email_id,
            "error":    "sagemaker_client_error",
            "message":  exc.response["Error"]["Message"],
        }))
        raise

    # Unwrap HuggingFace DLC double-encoding: [json_string, "application/json"]
    if isinstance(raw, list) and len(raw) == 2 and isinstance(raw[0], str):
        raw = json.loads(raw[0])

    predictions = raw.get("predictions") if isinstance(raw, dict) else None
    if not predictions or not isinstance(predictions, list):
        raise ValueError(f"Unexpected response format from endpoint: {raw}")

    pred = predictions[0]
    if not isinstance(pred, dict) or "intent" not in pred:
        raise ValueError(f"Prediction missing 'intent' key: {pred}")

    logger.info(json.dumps({
        "trace_id":      email_id,
        "op":            "biobert_prediction",
        "intent":        pred.get("intent"),
        "score":         pred.get("score"),
        "multi_intents": pred.get("multi_intents"),
    }))

    return pred
