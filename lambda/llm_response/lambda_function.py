"""
LLM Response Generation Lambda

Drafts a customer email response using a configurable primary model (default: mistral-7b),
then evaluates quality across 8 RAG dimensions using the other model as judge.
Confidence is derived from a weighted average of the evaluation scores.
"""
import json
import os
import sys
from typing import Dict, Any, Tuple, List
from datetime import datetime, timezone
from decimal import Decimal
import boto3

# Shared ReAct / CoT utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../shared'))
from reasoning_utils import extract_cot_answer, extract_react_answer, log_reasoning_trace

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
<s>[INST]
You are a senior customer service specialist for Laya Healthcare, an Irish health insurance company.
Draft a formal, empathetic, and accurate response to the customer email below.
Use ONLY information from the provided knowledge base and CRM data — never invent policy details.

STRICT FORMATTING RULES — follow exactly:
- Write ONLY the email body. Do NOT include a Subject line.
- Start directly with the greeting (e.g. "Dear [customer name],").
- Sign off with EXACTLY this format (replace ROUTING_TEAM with the appropriate team):
    Best regards,
    [ROUTING_TEAM]
    Laya Healthcare
  Derive the team from CRM/classification data (e.g. "Customer Service Team",
  "Claims Team", "Policy Renewals Team"). Default to "Customer Service Team" if unknown.
- Do NOT include placeholder text like [Your Name] or [Agent Name].
- CITATION RULES (mandatory):
  * When you use information from a knowledge base document, place a sequential numerical
    superscript citation immediately after the relevant sentence: e.g. "Claims must be
    submitted within 90 days of treatment [1]." or "You can renew online via MyLaya [2]."
  * Citations must be numbers only: [1], [2], [3] etc. matching the document numbers below.
  * Never write raw file names like [knowledge_base_renewal.txt_1] or [doc_id].
  * Never write a "Resources:", "References:", or "Further Reading" section.
  * Never say "please refer to the following documents" — the files are attached automatically.
  * Every factual policy claim MUST be backed by a citation number. Do not state policy
    rules without citing the document they came from.

CUSTOMER EMAIL
Subject: {subject}
Body: {body}

CUSTOMER INTENT: {intent}

CRM VALIDATION
{crm_validation}

FRAUD ASSESSMENT
{fraud_score}

KNOWLEDGE BASE DOCUMENTS
{rag_context}

Work through ALL steps carefully before producing the final response:

<reasoning>
Step 1 — Customer situation analysis:
  State the customer's exact intent and the specific question or problem they raise.
  List any key details: dates, amounts, policy/member numbers, plan name from CRM.
  Identify what outcome the customer needs.

Step 2 — CRM eligibility decision:
  crm_found=true/false? Policy status (active/lapsed/pending)? eligible_for_intent=true/false?
  State the governing rule that applies:
  - crm_found=false → must ask for verification; cannot discuss account details
  - crm_found=true, eligible=false → acknowledge intent, explain ineligibility clearly, guide next steps
  - crm_found=true, eligible=true → respond fully with verified plan-specific details
  Quote the relevant CRM fields (plan_name, policy_number, ineligibility_reason) that drive your response.

Step 3 — Knowledge base analysis:
  For each document [1], [2], [3]… state:
  a) What specific policy rule, procedure, amount or timeframe it contains
  b) Whether it is directly applicable to this customer's situation (yes/no — why)
  c) The exact sentence or fact you will cite in the response
  Only cite documents that are genuinely applicable. Discard irrelevant ones.

Step 4 — Fraud assessment:
  State the fraud score and risk level. Does it require any additional caution wording?

Step 5 — Response plan:
  Outline the response structure sentence by sentence before writing it:
  - Greeting and acknowledgement
  - Core answer (with which citation numbers support each point)
  - Next steps / action items for the customer
  - Sign-off team
  Confirm: every factual policy claim maps to a [citation number] from Step 3.
</reasoning>

FINAL_JSON: {{"response_text": "<email body only, starting with greeting, with [1] [2] citations>"}}
[/INST]"""

_EVALUATION_PROMPT = """\
<s>[INST]
You are an expert evaluator for a RAG-based insurance response system.
Score the response across 8 dimensions using step-by-step reasoning.

Question: {question}
Context: {context}
CRM Validation: {crm_validation}
Fraud Assessment: {fraud_score}
Answer: {answer}

Thought 1: Does the answer strictly follow the knowledge base context with no hallucination?
Action 1: CHECK_FAITHFULNESS
Observation 1: <your observation>

Thought 2: Does the answer directly address what the customer asked?
Action 2: CHECK_ANSWER_RELEVANCE
Observation 2: <your observation>

Thought 3: Is the response safe, legally compliant, and consistent with CRM/fraud data?
           Specifically: does it follow the crm_found/eligible_for_intent rules?
Action 3: CHECK_SAFETY_COMPLIANCE
Observation 3: <your observation>

Thought 4: Does the response avoid misleading or harmful guidance?
Action 4: CHECK_NO_HARMFUL_ADVICE
Observation 4: <your observation>

Thought 5: Does the response cover all key points raised in the email?
Action 5: CHECK_COMPLETENESS
Observation 5: <your observation>

Thought 6: Is the response clear and actionable?
Action 6: CHECK_HELPFULNESS
Observation 6: <your observation>

Thought 7: Are the retrieved context chunks relevant and precise for this query?
Action 7: CHECK_CONTEXT_PRECISION
Observation 7: <your observation>

Thought 8: Does the context cover all information needed to answer the query?
Action 8: CHECK_CONTEXT_RECALL
Observation 8: <your observation>

FINAL_ANSWER: {{"faithfulness": 0.xx, "answer_relevance": 0.xx, \
"context_precision": 0.xx, "context_recall": 0.xx, \
"completeness": 0.xx, "helpfulness": 0.xx, \
"safety_compliance": 0.xx, "no_harmful_advice": 0.xx}}
[/INST]"""


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
        route_team = (
            (classification.get('route_team') or classification.get('gold_route_team', ''))
            if isinstance(classification, dict) else ''
        ) or 'Customer Service Team'

        if not email_body:
            raise ValueError("Missing email_body in event")
        if active_model not in MODELS:
            raise ValueError(f"Unknown model '{active_model}'. Valid: {list(MODELS)}")

        # Step 1: Draft response with active model
        response_text, reference_ids, gen_metrics, gen_reasoning = generate_response(
            email_id, subject, email_body, intent,
            rag_documents, crm_validation, fraud_score, active_model, route_team,
        )

        # Step 2: Persist draft to email table
        if email_id:
            _update_email_response(email_id, response_text, reference_ids, gen_reasoning)

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
    route_team: str = 'Customer Service Team',
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
    raw_output, input_tokens, output_tokens = _invoke_model(
        model_config, prompt, task='generation'
    )
    latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

    # Extract CoT reasoning and FINAL_JSON response_text
    cot_reasoning, json_str = extract_cot_answer(raw_output)
    reasoning_format_valid = bool(cot_reasoning)

    # Build a full diagnostic trace that always includes inputs + model reasoning
    generation_trace = _build_generation_trace(
        email_id       = email_id,
        subject        = subject,
        body           = body,
        intent         = intent,
        crm_validation = crm_validation,
        fraud_score    = fraud_score,
        rag_documents  = rag_documents,
        cot_reasoning  = cot_reasoning,
        raw_output     = raw_output,
        model_name     = model_name,
    )

    log_reasoning_trace(
        logger_fn              = print,
        email_id               = email_id,
        lambda_name            = "llm_response_generation",
        scratchpad             = cot_reasoning or raw_output[:500],
        final_answer           = json_str[:300] if json_str else '',
        reasoning_format_valid = reasoning_format_valid,
    )

    # Try to extract response_text from FINAL_JSON; fall back to raw output
    try:
        parsed_json = json.loads(json_str) if json_str else {}
        response_text = parsed_json.get('response_text', '').strip() or raw_output.strip()
    except (json.JSONDecodeError, AttributeError):
        response_text = raw_output.strip()

    response_text = _clean_response(response_text, route_team=route_team)

    # Extract reference_ids from rag_documents
    reference_ids = [doc.get('doc_id', '') for doc in rag_documents if doc.get('doc_id')]

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
    return response_text, reference_ids, metrics, generation_trace


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
    raw_output, input_tokens, output_tokens = _invoke_model(
        model_config, prompt, task='evaluation'
    )
    latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

    # Extract ReAct scratchpad and FINAL_ANSWER scores JSON
    react_scratchpad, scores_json = extract_react_answer(raw_output)

    log_reasoning_trace(
        logger_fn              = print,
        email_id               = email_id,
        lambda_name            = "llm_response_evaluation",
        scratchpad             = react_scratchpad,
        final_answer           = scores_json[:300] if scores_json else '',
        reasoning_format_valid = bool(react_scratchpad),
    )

    eval_scores = _parse_eval_scores(scores_json if scores_json else raw_output)
    confidence  = _calculate_confidence(eval_scores, rag_documents)
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
    task: str = 'generation',
) -> Tuple[str, int, int]:
    """
    Call Bedrock; return (output_text, input_tokens, output_tokens).

    task='generation'  uses 3072 tokens (CoT reasoning ~400 + response ~600)
    task='evaluation'  uses 1024 tokens (8-step ReAct trace ~500 + JSON ~100)
    """
    model_id   = model_config['id']
    model_type = model_config['type']

    max_tokens = 1024 if task == 'evaluation' else 3072

    if model_type == 'mistral':
        request_body = {
            'prompt': prompt, 'max_tokens': max_tokens,
            'temperature': 0.15 if task == 'generation' else 0.1,
            'top_p': 0.9, 'top_k': 50,
        }
    elif model_type == 'meta':
        request_body = {
            'prompt': prompt, 'max_gen_len': max_tokens,
            'temperature': 0.15 if task == 'generation' else 0.1,
            'top_p': 0.9,
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
    """
    Parse judge output into {dimension: float 0-1}.

    The input may already be a FINAL_ANSWER JSON string (pre-extracted by evaluate_response)
    or raw model output. Tries JSON parse first; falls back to brace-depth extraction.
    Defaults to 0.5 for missing fields.
    """
    # Try direct JSON parse (already extracted via extract_react_answer)
    text = raw.strip()
    if not text.startswith('{'):
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


def _calculate_confidence(scores: Dict[str, float], rag_documents: List[Dict[str, Any]]) -> float:
    """
    Blended confidence: 50% weighted LLM judge score + 50% avg RAG similarity score.
    RAG score defaults to 0.0 when no documents are retrieved.
    """
    eval_score = sum(EVAL_WEIGHTS[k] * scores.get(k, 0.5) for k in EVAL_WEIGHTS)
    rag_scores = [
        float(doc['similarity_score'])
        for doc in rag_documents
        if 'similarity_score' in doc
    ]
    rag_score = sum(rag_scores) / len(rag_scores) if rag_scores else 0.0
    return round(0.5 * eval_score + 0.5 * rag_score, 4)


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
    generation_reasoning: str = '',
) -> None:
    """Persist the draft response, reference IDs, and CoT reasoning to the email record."""
    try:
        email_table.update_item(
            Key={'email_id': email_id},
            UpdateExpression=(
                'SET llm_response = :r, reference_ids = :ref, generation_reasoning = :gr'
            ),
            ExpressionAttributeValues={
                ':r':   response_text,
                ':ref': reference_ids,
                ':gr':  generation_reasoning[:3000] if generation_reasoning else '',
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

import re as _re

# Remove entire lines that consist only of a raw doc-ID/filename citation
# (e.g. "[knowledge_base_renewal.txt_1]") — numeric-only refs like [1] are preserved
_DOC_REF_LINE_RE = _re.compile(
    r'^[ \t]*[-*•]?[ \t]*\[[^\]]{3,120}\.(txt|pdf|docx|md)[^\]]*\][ \t]*$',
    _re.MULTILINE | _re.IGNORECASE,
)
# Remove inline raw filename/doc-id citations (preserves [1], [2] numeric citations)
_DOC_REF_RE = _re.compile(r'\[[^\]]{3,120}\.(txt|pdf|docx|md)[^\]]*\]', _re.IGNORECASE)
# Remove orphaned "refer to resources/documents" sentences left after citation lines are stripped
_REFER_TO_RE     = _re.compile(
    r',?\s*please\s+(refer\s+to|see|check|find)\s+(the\s+)?(following\s+)?(resources?|documents?|files?|links?|information\s+below)[^.:\n]*[.:]?',
    _re.IGNORECASE,
)
# Remove trailing "For more information, see:" / "Resources:" / "References:" headings
_RESOURCE_HDR_RE = _re.compile(
    r'\n?(For\s+more\s+information[^.\n]*\n)?[ \t]*(Resources?|References?|Further\s+Reading)[:\s]*\n?',
    _re.IGNORECASE,
)
_PLACEHOLDER_RE  = _re.compile(r'\[Your Name\]|\[Agent Name\]|\[Name\]', _re.IGNORECASE)
_SUBJECT_LINE_RE = _re.compile(r'^Subject:.*\n?', _re.IGNORECASE | _re.MULTILINE)
_SIGNOFF_RE      = _re.compile(
    r'(best regards|kind regards|yours sincerely|sincerely|regards)[,.]?\s*\n.*',
    _re.IGNORECASE | _re.DOTALL,
)


def _build_generation_trace(
    email_id: str,
    subject: str,
    body: str,
    intent: str,
    crm_validation: Dict[str, Any],
    fraud_score: Dict[str, Any],
    rag_documents: List[Dict[str, Any]],
    cot_reasoning: str,
    raw_output: str,
    model_name: str,
) -> str:
    """
    Build a human-readable diagnostic trace that always includes:
      1. Customer context (email, intent, CRM summary, fraud, RAG docs)
      2. Model's CoT reasoning if produced, otherwise the raw output
    Truncated to 1500 chars before DynamoDB storage.
    """
    lines = []

    # ── Inputs ────────────────────────────────────────────────────────────────
    lines.append(f"=== INPUTS  [{model_name}] ===")
    lines.append(f"Intent       : {intent}")
    lines.append(f"Subject      : {subject}")
    lines.append(f"Body snippet : {body[:120].replace(chr(10), ' ')}...")

    # CRM summary
    if crm_validation:
        crm_found   = crm_validation.get('crm_found', False)
        policy      = crm_validation.get('policy', {}) or {}
        customer    = crm_validation.get('customer', {}) or {}
        eligible    = crm_validation.get('eligible_for_intent', 'N/A')
        lines.append(
            f"CRM          : found={crm_found} | "
            f"customer={customer.get('full_name','?')} | "
            f"policy={policy.get('policy_number','?')} | "
            f"plan={policy.get('plan_name','?')} | "
            f"eligible={eligible}"
        )
    else:
        lines.append("CRM          : not available")

    # Fraud
    if fraud_score:
        lines.append(
            f"Fraud        : score={fraud_score.get('fraud_score','?')} | "
            f"risk={fraud_score.get('risk_level','?')}"
        )

    # RAG docs with citation numbers matching the prompt
    if rag_documents:
        lines.append("RAG docs     :")
        for i, d in enumerate(rag_documents[:6], start=1):
            title = _doc_human_title(d)
            lines.append(f"  [{i}] {title}")
    else:
        lines.append("RAG docs     : none")

    # ── Model reasoning ───────────────────────────────────────────────────────
    lines.append("\n=== MODEL REASONING ===")
    if cot_reasoning:
        lines.append(cot_reasoning)
    else:
        lines.append("[no <reasoning> tags produced — raw output below]")
        lines.append(raw_output.strip())

    return "\n".join(lines)


def _clean_response(text: str, route_team: str = 'Customer Service Team') -> str:
    """
    Post-process the model's response_text:
    1. Strip leading Subject: lines
    2. Remove inline RAG doc-ID citations like [filename.txt_2]
    3. Remove agent name placeholders
    4. Strip the model's sign-off and replace with the canonical signature:
         Best regards,
         <route_team>
         Laya Healthcare
    5. Collapse excess blank lines
    """
    text = _SUBJECT_LINE_RE.sub('', text)
    text = _DOC_REF_LINE_RE.sub('', text)    # remove whole-line citations first
    text = _DOC_REF_RE.sub('', text)          # then any inline remnants
    text = _RESOURCE_HDR_RE.sub('', text)     # remove "Resources:" / "References:" headings
    text = _REFER_TO_RE.sub('', text)         # remove orphaned "refer to resources" phrases
    text = _PLACEHOLDER_RE.sub('', text)
    text = _SIGNOFF_RE.sub('', text).rstrip()
    canonical_sig = f"Best regards,\n{route_team}\nLaya Healthcare"
    text = text + "\n\n" + canonical_sig
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _other_model(active_model: str) -> str:
    """Return the model name that is NOT the active model."""
    return next(m for m in MODELS if m != active_model)


def _source_key_to_title(source_key: str) -> str:
    """Derive a clean human-readable title from an S3 source_key or doc_id string."""
    name = source_key.split('/')[-1]                  # last path segment
    name = _re.sub(r'\.[a-z]{2,4}$', '', name)        # remove extension
    name = _re.sub(r'_\d+$', '', name)                # remove chunk index suffix
    name = _re.sub(r'^knowledge_base_?', '', name)    # strip kb prefix
    name = name.replace('_', ' ').replace('-', ' ').strip()
    return ' '.join(w.capitalize() for w in name.split()) or 'Laya Healthcare Policy Guide'


def _doc_human_title(doc: Dict[str, Any]) -> str:
    """Derive a clean human-readable title from a RAG document dict."""
    source_key = (doc.get('metadata') or {}).get('source_key', '') or doc.get('doc_id', '')
    return _source_key_to_title(source_key)


def _format_rag_context(rag_documents: List[Dict[str, Any]]) -> str:
    """
    Format RAG docs as numbered references with human-readable titles.
    Citation numbers [1], [2], … are stable within a single generation call
    and are used directly in the email body text.
    """
    if not rag_documents:
        return "No reference documents available."
    parts = []
    for i, doc in enumerate(rag_documents[:6], start=1):
        title   = _doc_human_title(doc)
        content = doc.get('content', '')[:700]
        parts.append(f"[{i}] {title}\n{content}")
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
