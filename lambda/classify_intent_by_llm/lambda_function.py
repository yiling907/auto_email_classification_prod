"""
Email Classification Lambda
Classifies inbound insurance emails across 7 label dimensions using a configurable
LLM model (default: mistral-7b), then evaluates classification accuracy using the
other available model as a judge.
"""
import json
import os
from typing import Dict, Any, Tuple
from datetime import datetime, timezone
from decimal import Decimal
import boto3
from botocore.exceptions import ClientError

# ── AWS clients ──────────────────────────────────────────────────────────────
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# ── Environment variables ────────────────────────────────────────────────────
MODEL_METRICS_TABLE_NAME = os.environ['MODEL_METRICS_TABLE_NAME']
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']
# Toggle: which model performs the primary classification.
# Can be overridden per-invocation via event['active_model'].
ACTIVE_MODEL = os.environ.get('ACTIVE_MODEL', 'mistral-7b')

model_metrics_table = dynamodb.Table(MODEL_METRICS_TABLE_NAME)
email_table = dynamodb.Table(EMAIL_TABLE_NAME)

# ── Model registry ───────────────────────────────────────────────────────────
MODELS = {
    'mistral-7b': {
        'id': 'mistral.mistral-7b-instruct-v0:2',
        'type': 'mistral',
        'cost_per_1k_input': 0.00015,
        'cost_per_1k_output': 0.00020,
    },
    'llama-3.1-8b': {
        'id': 'meta.llama3-8b-instruct-v1:0',
        'type': 'meta',
        'cost_per_1k_input': 0.00030,
        'cost_per_1k_output': 0.00060,
    },
}

# ── Schema enumerations ──────────────────────────────────────────────────────
VALID_INTENTS = {
    'coverage_query', 'claim_submission', 'claim_status',
    'claim_reimbursement_query', 'pre_authorisation', 'payment_issue',
    'policy_change', 'renewal_query', 'cancellation_request',
    'enrollment_new_policy', 'dependent_addition', 'complaint',
    'document_followup', 'hospital_network_query', 'id_verification',
    'broker_query', 'other',
}

VALID_URGENCY = {'low', 'medium', 'high'}
VALID_SENTIMENT = {'positive', 'neutral', 'frustrated', 'upset'}
VALID_PRIORITY = {'normal', 'high', 'urgent'}
VALID_ROUTE_TEAMS = {
    'claims_team', 'complaints_team', 'customer_support_team',
    'finance_support_team', 'general_support_team', 'medical_review_team',
    'operations_team', 'policy_admin_team', 'provider_support_team',
    'renewals_team', 'retention_team', 'sales_enrollment_team',
}

INTENT_TO_ROUTE = {
    'coverage_query':            'customer_support_team',
    'claim_submission':          'claims_team',
    'claim_status':              'claims_team',
    'claim_reimbursement_query': 'claims_team',
    'pre_authorisation':         'medical_review_team',
    'payment_issue':             'finance_support_team',
    'policy_change':             'policy_admin_team',
    'renewal_query':             'renewals_team',
    'cancellation_request':      'retention_team',
    'enrollment_new_policy':     'sales_enrollment_team',
    'dependent_addition':        'policy_admin_team',
    'complaint':                 'complaints_team',
    'document_followup':         'operations_team',
    'hospital_network_query':    'provider_support_team',
    'id_verification':           'operations_team',
    'broker_query':              'general_support_team',
    'other':                     'general_support_team',
}

CLASSIFICATION_FIELDS = (
    'customer_intent', 'secondary_intent', 'business_line',
    'urgency', 'sentiment', 'gold_route_team', 'gold_priority',
)

# ── Prompts ───────────────────────────────────────────────────────────────────
_CLASSIFICATION_PROMPT = """\
You are an AI assistant for an Irish health insurance company.
Classify the customer email below. Output ONLY a JSON object — no other text.

EMAIL SUBJECT: {subject}
EMAIL BODY: {body}

Valid values per field:
- customer_intent   : {intents}
- secondary_intent  : (same 17 values as customer_intent, or "" if none)
- business_line     : health_insurance
- urgency           : low | medium | high
- sentiment         : positive | neutral | frustrated | upset
- gold_route_team   : {teams}
- gold_priority     : normal | high | urgent
- requires_human_review : true | false  (true when complaint, pre_authorisation, or urgent priority)

{{"customer_intent": "...", "secondary_intent": "...", "business_line": "health_insurance", \
"urgency": "...", "sentiment": "...", "gold_route_team": "...", "gold_priority": "...", \
"requires_human_review": false}}"""

_ACCURACY_PROMPT = """\
You are a quality-assurance reviewer for a health insurance AI system.
An LLM classified the email below. Evaluate whether each field is correct (1) or incorrect (0).
Consider only what can be reasonably inferred from the email text.

EMAIL SUBJECT: {subject}
EMAIL BODY: {body}

CLASSIFICATION TO EVALUATE:
{classification}

Output ONLY a JSON object — no other text.
{{"customer_intent": <0|1>, "secondary_intent": <0|1>, "business_line": <0|1>, \
"urgency": <0|1>, "sentiment": <0|1>, "gold_route_team": <0|1>, "gold_priority": <0|1>}}"""


# ── Lambda handler ────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Classify a single inbound email and evaluate the classification accuracy.

    Event fields:
        email_id     (str)  — identifier stored in the email table
        email_body   (str)  — plain text body (also accepts 'body_text')
        subject      (str)  — email subject line (optional)
        active_model (str)  — override the default model toggle (optional)

    Returns:
        statusCode, email_id, active_model, classification, metrics, accuracy_evaluation
    """
    try:
        email_id   = event.get('email_id', '')
        email_body = event.get('email_body') or event.get('body_text', '')
        subject    = event.get('subject', '')
        active_model = (event.get('active_model') or ACTIVE_MODEL).strip()

        if not email_body:
            raise ValueError("Missing email_body in event")
        if active_model not in MODELS:
            raise ValueError(
                f"Unknown model '{active_model}'. Valid values: {list(MODELS)}"
            )

        # ── Step 1: classify with the active model ────────────────────────
        classification, clf_metrics = classify_email(
            email_id, subject, email_body, active_model
        )

        # ── Step 2: update email table ────────────────────────────────────
        if email_id:
            _update_email_record(email_id, classification)

        # ── Step 3: judge accuracy with the other model ───────────────────
        judge_model = _other_model(active_model)
        accuracy = evaluate_accuracy(
            email_id, subject, email_body, classification, judge_model
        )

        return {
            'statusCode': 200,
            'email_id': email_id,
            'active_model': active_model,
            'classification': classification,
            'metrics': clf_metrics,
            'accuracy_evaluation': accuracy,
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e),
            'results': [],
        }


# ── Classification ────────────────────────────────────────────────────────────

def classify_email(
    email_id: str,
    subject: str,
    body: str,
    model_name: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Invoke the chosen model to classify the email across 7 label dimensions.

    Returns:
        (classification_dict, metrics_dict)
    """
    model_config = MODELS[model_name]
    prompt = _CLASSIFICATION_PROMPT.format(
        subject=subject,
        body=body,
        intents=', '.join(sorted(VALID_INTENTS)),
        teams=', '.join(sorted(VALID_ROUTE_TEAMS)),
    )

    start = datetime.now(timezone.utc)
    raw_output, input_tokens, output_tokens = _invoke_model(model_config, prompt)
    latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

    classification = _parse_classification(raw_output)
    cost = _calculate_cost(input_tokens, output_tokens, model_config)
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    metrics = {
        'model_id':   model_config['id'],
        'model_name': model_name,
        'email_id':   email_id,
        'task_type':  'email_classification',
        'cost_usd':   cost,
        'latency_ms': latency_ms,
        'timestamp':  timestamp,
    }
    _store_metrics(metrics)

    print(
        f"Classified email {email_id!r} with {model_name}: "
        f"intent={classification.get('customer_intent')} "
        f"latency={latency_ms:.0f}ms cost=${cost:.6f}"
    )
    return classification, metrics


# ── Accuracy evaluation ───────────────────────────────────────────────────────

def evaluate_accuracy(
    email_id: str,
    subject: str,
    body: str,
    classification: Dict[str, Any],
    judge_model_name: str,
) -> Dict[str, Any]:
    """
    Use the judge model to score each classification field as 0 (wrong) or 1 (correct).

    Returns:
        {judge_model, per_field: {field: 0|1}, overall_score: float}
    """
    model_config = MODELS[judge_model_name]
    clf_summary = {f: classification.get(f, '') for f in CLASSIFICATION_FIELDS}
    prompt = _ACCURACY_PROMPT.format(
        subject=subject,
        body=body,
        classification=json.dumps(clf_summary, indent=2),
    )

    start = datetime.now(timezone.utc)
    raw_output, input_tokens, output_tokens = _invoke_model(model_config, prompt)
    latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

    per_field = _parse_accuracy(raw_output)
    overall = round(sum(per_field.values()) / len(per_field), 4) if per_field else 0.0
    cost = _calculate_cost(input_tokens, output_tokens, model_config)
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    eval_metrics = {
        'model_id':   model_config['id'],
        'model_name': judge_model_name,
        'email_id':   email_id,
        'task_type':  'accuracy_evaluation',
        'cost_usd':   cost,
        'latency_ms': latency_ms,
        'timestamp':  timestamp,
        'accuracy_scores': per_field,
        'overall_accuracy': overall,
    }
    _store_metrics(eval_metrics)

    print(
        f"Accuracy evaluation for {email_id!r} by {judge_model_name}: "
        f"overall={overall:.2f} per_field={per_field}"
    )
    return {
        'judge_model':  judge_model_name,
        'per_field':    per_field,
        'overall_score': overall,
    }


# ── Model invocation ──────────────────────────────────────────────────────────

def _invoke_model(
    model_config: Dict[str, Any],
    prompt: str,
) -> Tuple[str, int, int]:
    """
    Invoke a Bedrock model and return (output_text, input_tokens, output_tokens).
    """
    model_id   = model_config['id']
    model_type = model_config['type']

    if model_type == 'mistral':
        request_body = {
            'prompt': prompt,
            'max_tokens': 512,
            'temperature': 0.1,
            'top_p': 0.9,
            'top_k': 50,
        }
    elif model_type == 'meta':
        request_body = {
            'prompt': prompt,
            'max_gen_len': 512,
            'temperature': 0.1,
            'top_p': 0.9,
        }
    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    response = bedrock_runtime.invoke_model(
        modelId=model_id,
        body=json.dumps(request_body),
        contentType='application/json',
        accept='application/json',
    )
    response_body = json.loads(response['body'].read())

    if model_type == 'mistral':
        outputs = response_body.get('outputs', [])
        output_text = outputs[0].get('text', '') if outputs else ''
        input_tokens  = int(len(prompt.split()) * 1.3)
        output_tokens = int(len(output_text.split()) * 1.3)
    elif model_type == 'meta':
        output_text   = response_body.get('generation', '')
        input_tokens  = response_body.get('prompt_token_count', 0)
        output_tokens = response_body.get('generation_token_count', 0)
    else:
        output_text   = ''
        input_tokens  = 0
        output_tokens = 0

    return output_text, input_tokens, output_tokens


# ── Output parsers ─────────────────────────────────────────────────────────────

def _parse_classification(raw: str) -> Dict[str, Any]:
    """
    Parse model output into a validated classification dict.
    Falls back gracefully on malformed JSON.
    """
    text = _strip_fences(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        print(f"JSON parse error in classification output: {raw!r}")
        parsed = {}

    intent = str(parsed.get('customer_intent', '')).strip().lower()
    if intent not in VALID_INTENTS:
        intent = 'other'

    secondary = str(parsed.get('secondary_intent', '')).strip().lower()
    if secondary not in VALID_INTENTS:
        secondary = ''

    urgency = str(parsed.get('urgency', 'low')).strip().lower()
    if urgency not in VALID_URGENCY:
        urgency = 'low'

    sentiment = str(parsed.get('sentiment', 'neutral')).strip().lower()
    if sentiment not in VALID_SENTIMENT:
        sentiment = 'neutral'

    route = str(parsed.get('gold_route_team', '')).strip().lower()
    if route not in VALID_ROUTE_TEAMS:
        route = INTENT_TO_ROUTE.get(intent, 'general_support_team')

    priority = str(parsed.get('gold_priority', 'normal')).strip().lower()
    if priority not in VALID_PRIORITY:
        priority = 'normal'

    # Determine requires_human_review
    raw_review = parsed.get('requires_human_review', False)
    if isinstance(raw_review, bool):
        requires_review = raw_review
    else:
        requires_review = str(raw_review).lower() in ('true', '1', 'yes')
    # Override: complaints and pre_authorisations always need human review
    if intent in ('complaint', 'pre_authorisation') or priority == 'urgent':
        requires_review = True

    return {
        'customer_intent':      intent,
        'secondary_intent':     secondary,
        'business_line':        'health_insurance',
        'urgency':              urgency,
        'sentiment':            sentiment,
        'gold_route_team':      route,
        'gold_priority':        priority,
        'requires_human_review': requires_review,
    }


def _parse_accuracy(raw: str) -> Dict[str, int]:
    """
    Parse judge-model output into per-field binary scores {field: 0|1}.
    Defaults to 0 for any unparseable field.
    """
    text = _strip_fences(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        print(f"JSON parse error in accuracy output: {raw!r}")
        parsed = {}

    result = {}
    for field in CLASSIFICATION_FIELDS:
        val = parsed.get(field, 0)
        result[field] = 1 if str(val) in ('1', 'true', 'True') or val == 1 else 0
    return result


def _extract_json(text: str) -> str:
    """
    Extract the first complete JSON object from text by tracking brace depth.
    Handles preamble text and markdown code fences (e.g. Llama-style responses).
    """
    text = text.strip()
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


# Keep old name as alias for backward compatibility
def _strip_fences(text: str) -> str:
    return _extract_json(text)


# ── DynamoDB helpers ──────────────────────────────────────────────────────────

def _store_metrics(metrics: Dict[str, Any]) -> None:
    """
    Persist a metrics record.
    Primary key: metric_key = "{model_id}#{task_type}#{email_id}"
    """
    try:
        metric_key = f"{metrics['model_id']}#{metrics['task_type']}#{metrics['email_id']}"

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
        # Attach accuracy fields when present (accuracy_evaluation task)
        if 'accuracy_scores' in metrics:
            item['accuracy_scores'] = {k: int(v) for k, v in metrics['accuracy_scores'].items()}
            item['overall_accuracy'] = Decimal(str(metrics['overall_accuracy']))

        model_metrics_table.put_item(Item=item)
        print(f"Stored metrics: {metric_key}")

    except Exception as e:
        print(f"Error storing metrics: {str(e)}")
        raise


def _update_email_record(email_id: str, classification: Dict[str, Any]) -> None:
    """Update the email record with the 7 classification label fields."""
    try:
        email_table.update_item(
            Key={'email_id': email_id},
            UpdateExpression=(
                'SET customer_intent = :ci, secondary_intent = :si, '
                'business_line = :bl, urgency = :ug, sentiment = :se, '
                'gold_route_team = :rt, gold_priority = :gp, '
                'requires_human_review = :rhr, '
                'classification_timestamp = :ts'
            ),
            ExpressionAttributeValues={
                ':ci':  classification['customer_intent'],
                ':si':  classification['secondary_intent'],
                ':bl':  classification['business_line'],
                ':ug':  classification['urgency'],
                ':se':  classification['sentiment'],
                ':rt':  classification['gold_route_team'],
                ':gp':  classification['gold_priority'],
                ':rhr': classification['requires_human_review'],
                ':ts':  datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            },
        )
        print(f"Updated email record: {email_id}")
    except Exception as e:
        print(f"Error updating email record {email_id}: {str(e)}")
        raise


# ── Utility ───────────────────────────────────────────────────────────────────

def _other_model(active_model: str) -> str:
    """Return the model name that is NOT the active model."""
    others = [m for m in MODELS if m != active_model]
    return others[0]


def _calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model_config: Dict[str, Any],
) -> float:
    input_cost  = (input_tokens  / 1000) * model_config['cost_per_1k_input']
    output_cost = (output_tokens / 1000) * model_config['cost_per_1k_output']
    return round(input_cost + output_cost, 6)
