"""
inference.py — SageMaker serving script for DistilBertForSequenceClassification.

Model: fine-tuned DistilBERT, 5-class insurance intent classifier
Labels: billing | claim | complaint | coverage | policy

Packaged inside model.tar.gz alongside model files.
"""

import json
import logging
import os

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
logger.info("Inference device: %s", DEVICE)

MAX_LENGTH = 512   # DistilBERT max sequence length


# ─── 1. model_fn ─────────────────────────────────────────────────────────────
def model_fn(model_dir: str):
    """
    Load the DistilBERT model and tokenizer from model_dir (/opt/ml/model).
    Called once when the container starts.
    """
    logger.info("Loading model from %s on %s", model_dir, DEVICE)

    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    model.to(DEVICE)
    model.eval()

    logger.info(
        "Model loaded — labels: %s",
        list(model.config.id2label.values()),
    )
    return {"model": model, "tokenizer": tokenizer}


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

    # Normalise to a list of strings
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
    Tokenise the input texts and run a forward pass through DistilBERT.
    Returns a list of dicts: [{label: str, score: float, all_scores: {label: float}}]
    """
    model = model_artifacts["model"]
    tokenizer = model_artifacts["tokenizer"]
    id2label = model.config.id2label

    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=MAX_LENGTH,
        return_tensors="pt",
    )
    encoded = {k: v.to(DEVICE) for k, v in encoded.items()}

    with torch.no_grad():
        logits = model(**encoded).logits           # (batch, num_labels)
        probs = torch.softmax(logits, dim=-1)      # normalise to probabilities

    results = []
    for prob_row in probs:
        scores = {id2label[i]: round(float(p), 4) for i, p in enumerate(prob_row)}
        predicted_label = max(scores, key=scores.get)
        results.append({
            "label": predicted_label,
            "score": scores[predicted_label],
            "all_scores": scores,
        })
    return results


# ─── 4. output_fn ────────────────────────────────────────────────────────────
def output_fn(predictions: list, accept: str = "application/json"):
    """Serialise predictions to JSON."""
    if accept != "application/json":
        raise ValueError(f"Unsupported accept type: {accept}")
    return json.dumps({"predictions": predictions}), "application/json"
