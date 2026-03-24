"""
inference.py — SageMaker serving script for MultiLabelBioBERT insurance intent classifier.

Model: fine-tuned BioBERT, multi-label sigmoid classifier
Labels: loaded from labels.json (avoids numpy._core pickle dependency)
Routing: hardcoded INTENT_TO_ROUTE map

Packaged inside model.tar.gz alongside model files.
"""

import json
import logging
import os

import torch
from torch import nn
from transformers import AutoTokenizer, BertConfig, BertModel, BertPreTrainedModel

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
logger.info("Inference device: %s", DEVICE)

MAX_LENGTH = 512
THRESHOLD = 0.3

INTENT_TO_ROUTE = {
    "cancellation_request":      "retention_team",
    "claim_reimbursement_query": "claims_team",
    "claim_status":              "claims_team",
    "claim_submission":          "claims_team",
    "complaint":                 "complaints_team",
    "coverage_query":            "customer_support_team",
    "dependent_addition":        "policy_admin_team",
    "document_followup":         "operations_team",
    "enrollment_new_policy":     "sales_enrollment_team",
    "hospital_network_query":    "provider_support_team",
    "id_verification":           "operations_team",
    "broker_query":              "general_support_team",
    "other":                     "general_support_team",
    "payment_issue":             "finance_support_team",
    "policy_change":             "policy_admin_team",
    "pre_authorisation":         "medical_review_team",
    "renewal_query":             "renewals_team",
}


# ─── Model class (must match training definition) ─────────────────────────────

class MultiLabelBioBERT(BertPreTrainedModel):
    def __init__(self, config):
        super().__init__(config)
        self.bert = BertModel(config)
        self.dropout = nn.Dropout(0.1)
        self.classifier = nn.Linear(config.hidden_size, config.num_labels)
        self.post_init()

    def forward(self, input_ids=None, attention_mask=None, token_type_ids=None):
        outputs = self.bert(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
        )
        pooled_output = self.dropout(outputs.pooler_output)
        return self.classifier(pooled_output)


# ─── 1. model_fn ─────────────────────────────────────────────────────────────

def model_fn(model_dir: str, context=None):
    """
    Load MultiLabelBioBERT, tokenizer, and mlb label binarizer.
    Called once when the container starts.
    """
    logger.info("Loading model from %s on %s", model_dir, DEVICE)

    # Load labels from JSON (avoids numpy._core pickle dependency from mlb.pkl)
    labels_path = os.path.join(model_dir, "labels.json")
    with open(labels_path) as f:
        classes = json.load(f)
    num_labels = len(classes)
    logger.info("Label classes (%d): %s", num_labels, classes)

    # Patch config with num_labels before loading model weights
    config = BertConfig.from_pretrained(model_dir)
    config.num_labels = num_labels

    model = MultiLabelBioBERT.from_pretrained(model_dir, config=config)
    model.to(DEVICE)
    model.eval()

    tokenizer = AutoTokenizer.from_pretrained(model_dir)

    logger.info("MultiLabelBioBERT loaded — %d labels", num_labels)
    return {
        "model":     model,
        "tokenizer": tokenizer,
        "classes":   classes,
    }


# ─── 2. input_fn ─────────────────────────────────────────────────────────────

def input_fn(request_body: bytes, content_type: str = "application/json"):
    """
    Deserialise the HTTP request body.

    Accepted formats:
      {"instances": ["text1", "text2"]}   — batch
      {"text": "single text"}             — single
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

def _predict_one(text: str, model, tokenizer, classes) -> dict:
    """Run multi-label sigmoid inference on a single text."""
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=MAX_LENGTH,
    )
    inputs.pop("token_type_ids", None)
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}

    with torch.no_grad():
        logits = model(**inputs)

    probs = torch.sigmoid(logits).cpu().numpy()[0]

    # Top-2 indices by probability
    top_indices = probs.argsort()[-2:][::-1]
    top_probs   = [float(probs[i]) for i in top_indices]

    # Apply threshold
    multi_intents = [classes[i] for i in top_indices if probs[i] >= THRESHOLD]

    # Always keep at least the highest-probability class
    if not multi_intents:
        multi_intents = [classes[top_indices[0]]]

    # Smart multi-detection: if top-2 are within 0.15 of each other → ambiguous → "other"
    if len(top_probs) >= 2 and abs(top_probs[0] - top_probs[1]) < 0.15:
        multi_intents = [classes[top_indices[0]], classes[top_indices[1]]]

    final_intent = "other" if len(multi_intents) > 1 else multi_intents[0]

    all_scores = {classes[i]: round(float(probs[i]), 4) for i in range(len(classes))}

    return {
        "intent":        final_intent,
        "score":         round(top_probs[0], 4),
        "multi_intents": multi_intents,
        "route_team":    INTENT_TO_ROUTE.get(final_intent, "general_support_team"),
        "all_scores":    all_scores,
    }


def predict_fn(texts: list, model_artifacts: dict) -> list:
    model     = model_artifacts["model"]
    tokenizer = model_artifacts["tokenizer"]
    classes   = model_artifacts["classes"]
    return [_predict_one(t, model, tokenizer, classes) for t in texts]


# ─── 4. output_fn ────────────────────────────────────────────────────────────

def output_fn(predictions: list, accept: str = "application/json"):
    """Serialise predictions to JSON."""
    if accept != "application/json":
        raise ValueError(f"Unsupported accept type: {accept}")
    return json.dumps({"predictions": predictions}), "application/json"
