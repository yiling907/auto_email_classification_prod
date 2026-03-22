"""
inference.py — SageMaker serving script for BioBERT insurance intent classifier.

Model: fine-tuned BioBERT, 15-class insurance intent classifier
Labels: hardcoded in INTENT_LABELS (matches sklearn LabelEncoder alphabetical order)
Routing: loaded from routing_map.pkl

Packaged inside model.tar.gz alongside model files.
"""

import json
import logging
import os
import pickle

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
logger.info("Inference device: %s", DEVICE)

MAX_LENGTH = 512

# Label order matches sklearn LabelEncoder.classes_ (alphabetical)
INTENT_LABELS = [
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
    "other",
    "payment_issue",
    "policy_change",
    "pre_authorisation",
    "renewal_query",
]


# ─── 1. model_fn ─────────────────────────────────────────────────────────────
def model_fn(model_dir: str, context=None):
    """
    Load the BioBERT model, tokenizer, and routing map.
    Called once when the container starts.
    """
    logger.info("Loading model from %s on %s", model_dir, DEVICE)

    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    model.to(DEVICE)
    model.eval()

    # Load routing map {intent: team} — plain dict, no numpy dependency
    routing_path = os.path.join(model_dir, "routing_map.pkl")
    with open(routing_path, "rb") as f:
        routing_map = pickle.load(f)

    logger.info("Model loaded — %d intent labels", len(INTENT_LABELS))
    return {
        "model": model,
        "tokenizer": tokenizer,
        "routing_map": routing_map,
    }


# ─── 2. input_fn ─────────────────────────────────────────────────────────────
def input_fn(request_body: bytes, content_type: str = "application/json"):
    """
    Deserialise the HTTP request body.

    Accepted formats:
      {"instances": ["I need help with my claim"]}          — batch of texts
      {"text": "I need help with my claim"}                 — single text
    """
    if content_type != "application/json":
        raise ValueError(f"Unsupported content_type: {content_type}")

    body = json.loads(request_body)

    if "instances" in body:
        texts = body["instances"]
    elif "text" in body:
        texts = [body["text"]] if isinstance(body["text"], str) else body["text"]
    else:
        raise ValueError("Request body must contain 'instances' (list) or 'text' (string).")

    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        raise ValueError("'instances' must be a list of strings.")

    return texts


# ─── 3. predict_fn ───────────────────────────────────────────────────────────
def predict_fn(texts: list, model_artifacts: dict):
    """
    Tokenise the input texts and run a forward pass through BioBERT.
    Returns a list of dicts: [{intent, score, route_team, all_scores}]
    """
    model = model_artifacts["model"]
    tokenizer = model_artifacts["tokenizer"]
    routing_map = model_artifacts["routing_map"]

    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=MAX_LENGTH,
        return_tensors="pt",
    )
    encoded = {k: v.to(DEVICE) for k, v in encoded.items()}

    with torch.no_grad():
        logits = model(**encoded).logits
        probs = torch.softmax(logits, dim=-1)

    results = []
    for prob_row in probs:
        scores = {INTENT_LABELS[i]: round(float(p), 4) for i, p in enumerate(prob_row)}
        predicted_intent = max(scores, key=scores.get)
        results.append({
            "intent": predicted_intent,
            "score": scores[predicted_intent],
            "route_team": routing_map.get(predicted_intent, "general_support_team"),
            "all_scores": scores,
        })
    return results


# ─── 4. output_fn ────────────────────────────────────────────────────────────
def output_fn(predictions: list, accept: str = "application/json"):
    """Serialise predictions to JSON."""
    if accept != "application/json":
        raise ValueError(f"Unsupported accept type: {accept}")
    return json.dumps({"predictions": predictions}), "application/json"
