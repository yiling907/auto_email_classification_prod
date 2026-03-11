"""
LLM Response Generation Lambda

Drafts a customer email response using a configurable primary model (default: mistral-7b),
then evaluates quality across 8 RAG dimensions using the other model as judge.
Confidence is derived from a weighted average of the evaluation scores.
"""
import json
import os
from typing import Dict, Any, Tuple, List
from datetime import datetime, timezone
from decimal import Decimal
import boto3

# ── AWS clients ───────────────────────────────────────────────────────────────
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# ── Environment variables ─────────────────────────────────────────────────────
EMAIL_TABLE_NAME         = os.environ['EMAIL_TABLE_NAME']
MODEL_METRICS_TABLE_NAME = os.environ['MODEL_METRICS_TABLE_NAME']
# Toggle: which model drafts the response. Override per-invocation via event['active_model'].
ACTIVE_MODEL             = os.environ.get('ACTIVE_MODEL', 'mistral-7b')

email_table         = dynamodb.Table(EMAIL_TABLE_NAME)
model_metrics_table = dynamodb.Table(MODEL_METRICS_TABLE_NAME)

# ── Model registry ────────────────────────────────────────────────────────────
MODELS = {
    'mistral-7b': {
        'id':                 'mistral.mistral-7b-instruct-v0:2',
        'type':               'mistral',
        'cost_per_1k_input':  0.00015,
        'cost_per_1k_output': 0.00020,
    },
    'llama-3.1-8b': {
        'id':                 'meta.llama3-8b-instruct-v1:0',
        'type':               'meta',
        'cost_per_1k_input':  0.00030,
        'cost_per_1k_output': 0.00060,
    },
}

# ── Evaluation weights (must sum to 1.0) ──────────────────────────────────────
EVAL_WEIGHTS = {
    'faithfulness':      0.25,   # No hallucination — critical for insurance
    'answer_relevance':  0.20,   # Directly addresses the customer's question
    'safety_compliance': 0.20,   # Legally safe and regulatory-compliant
    'no_harmful_advice': 0.15,   # Avoids misleading or harmful guidance
    'completeness':      0.10,   # Covers all key points raised
    'helpfulness':       0.05,   # Clear and actionable
    'context_precision': 0.025,  # Retrieved chunks are relevant
    'context_recall':    0.025,  # Context covers what is needed
}

# ── Prompts ───────────────────────────────────────────────────────────────────
_GENERATION_PROMPT = """\
You are a professional customer service agent for an Irish health insurance company.
Draft a response to the customer email below. Be accurate, professional and empathetic.
Reference ONLY the provided knowledge base documents — do not invent policy details.

CUSTOMER EMAIL
Subject: {subject}
Body: {body}

CUSTOMER INTENT: {intent}

CRM VALIDATION
{crm_validation}

FRAUD ASSESSMENT
{fraud_score}

KNOWLEDGE BASE CONTEXT
{rag_context}

Output ONLY a JSON object — no other text:
{{"response_text": "<full email response>", "reference_ids": ["<doc_id1>", ...]}}"""

_EVALUATION_PROMPT = """\
You are an expert evaluator for a RAG system.
Please assess the answer based on the context and question.

Question: {question}
Context: {context}
CRM Validation: {crm_validation}
Fraud Assessment: {fraud_score}
Answer: {answer}

Evaluate on a scale of 0-1 for each dimension:
1. faithfulness: Does the answer strictly follow the context, no hallucination?
2. answer_relevance: Does the answer directly address the question?
3. context_precision: Are the retrieved context chunks relevant and precise?
4. context_recall: Does the context cover all information needed to answer?
5. completeness: Does the answer fully cover all key points in the question?
6. helpfulness: Is the answer clear and useful for the user?
7. safety_compliance: Is the response legally safe, compliant, and consistent with CRM/fraud data?
8. no_harmful_advice: Does the response avoid harmful, misleading or incorrect advice?

Output ONLY JSON:
{{"faithfulness": 0.xx, "answer_relevance": 0.xx, "context_precision": 0.xx, \
"context_recall": 0.xx, "completeness": 0.xx, "helpfulness": 0.xx, \
"safety_compliance": 0.xx, "no_harmful_advice": 0.xx}}"""


# ── Lambda handler ─────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Event fields:
        email_id        (str)  — stored in email table
        email_body      (str)  — plain text body (also accepts 'body')
        subject         (str)  — email subject line
        active_model    (str)  — override ACTIVE_MODEL env var (optional)
        rag_documents   (list) — retrieved RAG docs
        classification  (dict) — classification result from classify_intent
        crm_validation  (dict) — CRM policy/customer validation data
        fraud_score     (dict) — fraud risk assessment data
    """
    try:
        email_id       = event.get('email_id', '')
        email_body     = event.get('email_body') or event.get('body', '')
        subject        = event.get('subject', '')
        active_model   = (event.get('active_model') or ACTIVE_MODEL).strip()
        rag_documents  = event.get('rag_documents', [])
        crm_validation = event.get('crm_validation') or {}
        fraud_score    = event.get('fraud_score') or {}
        classification = event.get('classification') or {}
        intent = (
            classification.get('customer_intent')
            if isinstance(classification, dict)
            else str(classification or 'unknown')
        )

        if not email_body:
            raise ValueError("Missing email_body in event")
        if active_model not in MODELS:
            raise ValueError(f"Unknown model '{active_model}'. Valid: {list(MODELS)}")

        # Step 1: Draft response with active model
        response_text, reference_ids, gen_metrics = generate_response(
            email_id, subject, email_body, intent,
            rag_documents, crm_validation, fraud_score, active_model,
        )

        # Step 2: Persist draft to email table
        if email_id:
            _update_email_response(email_id, response_text, reference_ids)

        # Step 3: Evaluate with judge model across 8 dimensions
        judge_model = _other_model(active_model)
        eval_scores, confidence, _ = evaluate_response(
            email_id, email_body, subject,
            rag_documents, crm_validation, fraud_score, response_text, judge_model,
        )

        # Step 4: Determine action from weighted confidence
        if confidence >= 0.8:
            action, confidence_level = 'auto_response', 'high'
        elif confidence >= 0.5:
            action, confidence_level = 'human_review', 'medium'
        else:
            action, confidence_level = 'escalate', 'low'

        # Step 5: Update email table with confidence and action
        if email_id:
            _update_confidence(email_id, confidence, confidence_level, action)

        print(
            f"Response generated for {email_id!r}: "
            f"model={active_model} confidence={confidence:.3f} action={action}"
        )
        return {
            'statusCode':       200,
            'email_id':         email_id,
            'active_model':     active_model,
            'response_text':    response_text,
            'reference_ids':    reference_ids,
            'confidence_score': confidence,
            'confidence_level': confidence_level,
            'action':           action,
            'evaluation':       eval_scores,
        }

    except Exception as e:
        print(f"Error: {e}")
        return {
            'statusCode':       500,
            'error':            str(e),
            'confidence_score': 0.0,
            'action':           'escalate',
        }


# ── Response generation ────────────────────────────────────────────────────────

def generate_response(
    email_id: str,
    subject: str,
    body: str,
    intent: str,
    rag_documents: List[Dict[str, Any]],
    crm_validation: Dict[str, Any],
    fraud_score: Dict[str, Any],
    model_name: str,
) -> Tuple[str, List[str], Dict[str, Any]]:
    """Draft a response with the active model. Returns (response_text, reference_ids, metrics)."""
    model_config = MODELS[model_name]
    rag_context  = _format_rag_context(rag_documents)
    prompt = _GENERATION_PROMPT.format(
        subject=subject,
        body=body,
        intent=intent,
        crm_validation=json.dumps(crm_validation, indent=2) if crm_validation else 'Not available',
        fraud_score=json.dumps(fraud_score, indent=2) if fraud_score else 'Not available',
        rag_context=rag_context,
    )

    start = datetime.now(timezone.utc)
    raw_output, input_tokens, output_tokens = _invoke_model(model_config, prompt)
    latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

    text = _extract_json(raw_output)
    try:
        parsed        = json.loads(text)
        response_text = str(parsed.get('response_text', raw_output[:3000]))
        reference_ids = list(parsed.get('reference_ids', []))
    except json.JSONDecodeError:
        response_text = raw_output[:3000]
        reference_ids = []

    cost      = _calculate_cost(input_tokens, output_tokens, model_config)
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    metrics = {
        'model_id':   model_config['id'],
        'model_name': model_name,
        'email_id':   email_id,
        'task_type':  'response_generation',
        'cost_usd':   cost,
        'latency_ms': latency_ms,
        'timestamp':  timestamp,
    }
    _store_metrics(metrics)

    print(
        f"Draft for {email_id!r} by {model_name}: "
        f"latency={latency_ms:.0f}ms cost=${cost:.6f}"
    )
    return response_text, reference_ids, metrics


# ── Response evaluation ────────────────────────────────────────────────────────

def evaluate_response(
    email_id: str,
    email_body: str,
    subject: str,
    rag_documents: List[Dict[str, Any]],
    crm_validation: Dict[str, Any],
    fraud_score: Dict[str, Any],
    response_text: str,
    model_name: str,
) -> Tuple[Dict[str, float], float, Dict[str, Any]]:
    """Score the response across 8 dimensions. Returns (eval_scores, confidence, metrics)."""
    model_config = MODELS[model_name]
    rag_context  = _format_rag_context(rag_documents)
    prompt = _EVALUATION_PROMPT.format(
        question=f"Subject: {subject}\n{email_body}",
        context=rag_context,
        crm_validation=json.dumps(crm_validation, indent=2) if crm_validation else 'Not available',
        fraud_score=json.dumps(fraud_score, indent=2) if fraud_score else 'Not available',
        answer=response_text,
    )

    start = datetime.now(timezone.utc)
    raw_output, input_tokens, output_tokens = _invoke_model(model_config, prompt)
    latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

    eval_scores = _parse_eval_scores(raw_output)
    confidence  = _calculate_confidence(eval_scores)
    cost        = _calculate_cost(input_tokens, output_tokens, model_config)
    timestamp   = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    metrics = {
        'model_id':         model_config['id'],
        'model_name':       model_name,
        'email_id':         email_id,
        'task_type':        'response_evaluation',
        'cost_usd':         cost,
        'latency_ms':       latency_ms,
        'timestamp':        timestamp,
        'eval_scores':      eval_scores,
        'confidence_score': confidence,
    }
    _store_metrics(metrics)

    print(
        f"Evaluation for {email_id!r} by {model_name}: "
        f"confidence={confidence:.3f} scores={eval_scores}"
    )
    return eval_scores, confidence, metrics


# ── Model invocation ──────────────────────────────────────────────────────────

def _invoke_model(
    model_config: Dict[str, Any],
    prompt: str,
) -> Tuple[str, int, int]:
    """Call Bedrock; return (output_text, input_tokens, output_tokens)."""
    model_id   = model_config['id']
    model_type = model_config['type']

    if model_type == 'mistral':
        request_body = {
            'prompt': prompt, 'max_tokens': 2048,
            'temperature': 0.1, 'top_p': 0.9, 'top_k': 50,
        }
    elif model_type == 'meta':
        request_body = {
            'prompt': prompt, 'max_gen_len': 2048,
            'temperature': 0.1, 'top_p': 0.9,
        }
    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    response      = bedrock_runtime.invoke_model(
        modelId=model_id,
        body=json.dumps(request_body),
        contentType='application/json',
        accept='application/json',
    )
    response_body = json.loads(response['body'].read())

    if model_type == 'mistral':
        outputs       = response_body.get('outputs', [])
        output_text   = outputs[0].get('text', '') if outputs else ''
        input_tokens  = int(len(prompt.split()) * 1.3)
        output_tokens = int(len(output_text.split()) * 1.3)
    else:  # meta
        output_text   = response_body.get('generation', '')
        input_tokens  = response_body.get('prompt_token_count', 0)
        output_tokens = response_body.get('generation_token_count', 0)

    return output_text, input_tokens, output_tokens


# ── Output parsers ────────────────────────────────────────────────────────────

def _parse_eval_scores(raw: str) -> Dict[str, float]:
    """Parse judge output into {dimension: float 0-1}. Defaults to 0.5 on missing fields."""
    text = _extract_json(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        print(f"JSON parse error in evaluation output: {raw!r}")
        parsed = {}

    result = {}
    for field in EVAL_WEIGHTS:
        val = parsed.get(field, 0.5)
        try:
            result[field] = max(0.0, min(1.0, float(val)))
        except (TypeError, ValueError):
            result[field] = 0.5
    return result


def _calculate_confidence(scores: Dict[str, float]) -> float:
    """Weighted average of evaluation scores → scalar confidence."""
    total = sum(EVAL_WEIGHTS[k] * scores.get(k, 0.5) for k in EVAL_WEIGHTS)
    return round(total, 4)


def _extract_json(text: str) -> str:
    """Extract the first complete JSON object by tracking brace depth."""
    text  = text.strip()
    start = text.find('{')
    if start == -1:
        return text
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text


# ── DynamoDB helpers ──────────────────────────────────────────────────────────

def _store_metrics(metrics: Dict[str, Any]) -> None:
    """Write a metrics record. PK: metric_key = '{model_id}#{task_type}#{email_id}'."""
    try:
        metric_key = (
            f"{metrics['model_id']}#{metrics['task_type']}#{metrics['email_id']}"
        )
        item: Dict[str, Any] = {
            'metric_key': metric_key,
            'model_id':   metrics['model_id'],
            'model_name': metrics['model_name'],
            'email_id':   metrics['email_id'],
            'task_type':  metrics['task_type'],
            'cost_usd':   Decimal(str(round(metrics['cost_usd'], 6))),
            'latency_ms': Decimal(str(round(metrics['latency_ms'], 2))),
            'timestamp':  metrics['timestamp'],
        }
        if 'eval_scores' in metrics:
            item['eval_scores']      = {k: str(v) for k, v in metrics['eval_scores'].items()}
            item['confidence_score'] = Decimal(str(metrics['confidence_score']))

        model_metrics_table.put_item(Item=item)
        print(f"Stored metrics: {metric_key}")
    except Exception as e:
        print(f"Error storing metrics: {e}")
        raise


def _update_email_response(
    email_id: str,
    response_text: str,
    reference_ids: List[str],
) -> None:
    """Persist the draft response and reference IDs to the email record."""
    try:
        email_table.update_item(
            Key={'email_id': email_id},
            UpdateExpression='SET llm_response = :r, reference_ids = :ref',
            ExpressionAttributeValues={
                ':r':   response_text,
                ':ref': reference_ids,
            },
        )
        print(f"Stored draft response for: {email_id}")
    except Exception as e:
        print(f"Error storing draft response: {e}")
        raise


def _update_confidence(
    email_id: str,
    confidence: float,
    confidence_level: str,
    action: str,
) -> None:
    """Update confidence score, level, and routing action on the email record."""
    try:
        email_table.update_item(
            Key={'email_id': email_id},
            UpdateExpression=(
                'SET confidence_score = :cs, confidence_level = :cl, '
                '#action_attr = :a, processing_status = :s, response_timestamp = :ts'
            ),
            ExpressionAttributeNames={'#action_attr': 'action'},
            ExpressionAttributeValues={
                ':cs': str(confidence),
                ':cl': confidence_level,
                ':a':  action,
                ':s':  'completed',
                ':ts': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            },
        )
        print(f"Updated confidence for {email_id}: {action}")
    except Exception as e:
        print(f"Error updating confidence: {e}")
        raise


# ── Utility ───────────────────────────────────────────────────────────────────

def _other_model(active_model: str) -> str:
    """Return the model name that is NOT the active model."""
    return next(m for m in MODELS if m != active_model)


def _format_rag_context(rag_documents: List[Dict[str, Any]]) -> str:
    """Format RAG docs into a numbered context block."""
    if not rag_documents:
        return "No reference documents available."
    parts = []
    for doc in rag_documents[:5]:
        doc_id  = doc.get('doc_id', 'unknown')
        content = doc.get('content', '')[:600]
        parts.append(f"[{doc_id}] {content}")
    return "\n\n".join(parts)


def _calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model_config: Dict[str, Any],
) -> float:
    return round(
        (input_tokens  / 1000) * model_config['cost_per_1k_input'] +
        (output_tokens / 1000) * model_config['cost_per_1k_output'],
        6,
    )
