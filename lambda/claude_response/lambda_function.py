"""
Claude Response Generation Lambda Function
Generates high-confidence insurance email responses using Claude 3
"""
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']

# Using open-source models for cost optimization
# Primary model for production responses (can be overridden via env var)
PRIMARY_MODEL_ID = os.environ.get('PRIMARY_MODEL_ID', 'mistral.mistral-7b-instruct-v0:2')

# Evaluator model: always different from primary to get an independent quality signal
# Default to Claude Haiku (cheap, reliable judge)
EVALUATOR_MODEL_ID = os.environ.get('EVALUATOR_MODEL_ID', 'anthropic.claude-3-haiku-20240307-v1:0')

# Available open-source models for fallback (in priority order)
FALLBACK_MODELS = [
    'mistral.mistral-7b-instruct-v0:2',       # Mistral 7B: $0.15/$0.20 per 1M tokens (cheapest & reliable)
    'us.meta.llama3-1-8b-instruct-v1:0',      # Llama 3.1 8B: $0.30/$0.60 per 1M (inference profile)
    # Removed: amazon.titan-text-express-v1 (EOL - end of life)
]

# Task-type-specific accuracy criteria for the evaluator
TASK_TYPE_CRITERIA = {
    'claim': [
        "Accurately describes the claim review/processing timeline without guaranteeing outcomes",
        "References relevant policy coverage clauses where applicable",
        "Provides clear next steps the customer must take",
        "Does not approve or deny the claim without verification",
    ],
    'enrollment': [
        "Accurately states eligibility requirements without over-promising",
        "Provides correct open enrollment period information",
        "Clearly explains the enrollment steps in order",
        "Does not confirm enrollment before verification is complete",
    ],
    'policy/account': [
        "Correctly references policy terms without legal misrepresentation",
        "Accurately describes account management options available",
        "Includes appropriate disclaimers for policy interpretations",
        "Does not make binding commitments about policy outcomes",
    ],
    'complaint': [
        "Acknowledges the customer's concern with empathy and professionalism",
        "Provides a clear resolution path or escalation to a specialist",
        "Does not dismiss or minimise the complaint",
        "Offers concrete next steps with expected timeframe",
    ],
    'inquiry': [
        "Fully addresses the customer's specific question",
        "Provides accurate and relevant information from knowledge base",
        "Is clear, concise, and avoids unnecessary jargon",
        "Includes appropriate caveats where information may vary",
    ],
    'billing_inquiry': [
        "Accurately addresses the billing or payment question",
        "Does not reveal or misstate sensitive financial details",
        "Provides clear payment options or next steps",
        "References correct billing policies and timelines",
    ],
    'technicalissue': [
        "Provides actionable troubleshooting steps in clear order",
        "Escalates to technical support when issue is beyond scope",
        "Does not make promises about resolution time",
        "Confirms what information will be needed from the customer",
    ],
    'spam': [
        "Response is appropriately brief and does not engage with spam content",
        "Does not leak any sensitive policy or account information",
        "Maintains professional tone",
    ],
    'medicalservice': [
        "Accurately describes what is covered under the medical benefit",
        "Does not provide medical advice or diagnoses",
        "References the correct benefit schedule or plan document",
        "Includes appropriate healthcare disclaimer",
    ],
}

email_table = dynamodb.Table(EMAIL_TABLE_NAME)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for Claude response generation

    Args:
        event: Contains email data, entities, intent, RAG context
        context: Lambda context

    Returns:
        Dict with generated response and confidence score
    """
    try:
        # Extract input data
        email_id = event.get('email_id')
        email_body = event.get('email_body') or event.get('body')
        subject = event.get('subject', '')
        entities = event.get('entities', {})
        intent_data = event.get('intent', {})
        rag_documents = event.get('rag_documents', [])
        crm_validation = event.get('crm_validation', {})
        fraud_score = event.get('fraud_score', {})

        if not email_body:
            raise ValueError("Missing email_body in event")

        # Extract intent from multi-LLM results (find first successful result)
        intent = 'unknown'
        if isinstance(intent_data, dict) and 'results' in intent_data:
            for result in intent_data.get('results', []):
                if result.get('success') and result.get('output_text'):
                    intent = result['output_text']
                    break
        elif isinstance(intent_data, str):
            intent = intent_data

        print(f"Generating response for email: {email_id}")
        print(f"Intent: {intent}, RAG docs: {len(rag_documents)}")

        # Build prompt with RAG context
        prompt = build_prompt(
            email_body=email_body,
            subject=subject,
            entities=entities,
            intent=intent,
            rag_documents=rag_documents,
            crm_validation=crm_validation,
            fraud_score=fraud_score
        )

        # Call Claude 3
        start_time = datetime.utcnow()
        response_data = invoke_claude(prompt)
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        # Parse response
        parsed_response = parse_claude_response(response_data)

        # Determine action based on confidence
        confidence = parsed_response['confidence_score']
        if confidence >= 0.8:
            action = 'auto_response'
            confidence_level = 'high'
        elif confidence >= 0.5:
            action = 'human_review'
            confidence_level = 'medium'
        else:
            action = 'escalate'
            confidence_level = 'low'

        # Evaluate response quality with a separate model (LLM-as-judge)
        evaluation = evaluate_response(
            email_body=email_body,
            response_text=parsed_response['response_text'],
            intent=intent,
            rag_documents=rag_documents,
            primary_model_id=PRIMARY_MODEL_ID
        )

        # Prepare result
        result = {
            'statusCode': 200,
            'email_id': email_id,
            'response_text': parsed_response['response_text'],
            'confidence_score': confidence,
            'confidence_level': confidence_level,
            'action': action,
            'reference_ids': parsed_response.get('reference_ids', []),
            'compliance_checks': parsed_response.get('compliance_checks', {}),
            'latency_ms': latency_ms,
            'model_id': PRIMARY_MODEL_ID,
            'evaluation': evaluation,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }

        # Update DynamoDB if email_id provided
        if email_id:
            update_email_record(email_id, result, confidence_level)

        return result

    except ClientError as e:
        print(f"AWS Error: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e),
            'confidence_score': 0.0,
            'action': 'escalate'
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e),
            'confidence_score': 0.0,
            'action': 'escalate'
        }


def build_prompt(
    email_body: str,
    subject: str,
    entities: Dict[str, Any],
    intent: str,
    rag_documents: List[Dict[str, Any]],
    crm_validation: Dict[str, Any],
    fraud_score: Dict[str, Any]
) -> str:
    """Build structured prompt for Claude"""

    # Extract RAG context
    rag_context = "\n\n".join([
        f"[Reference {i+1}] {doc.get('content', '')[:500]}"
        for i, doc in enumerate(rag_documents[:3])
    ]) if rag_documents else "No reference documents available."

    prompt = f"""You are an AI assistant for an insurance company. Your task is to analyze the following email and generate an appropriate response.

INSURANCE COMPLIANCE GUIDELINES:
- Always be accurate and factual
- Reference policy documents when making statements
- Never guarantee outcomes without verification
- Include appropriate disclaimers
- Maintain professional tone

EMAIL DETAILS:
Subject: {subject}
Body: {email_body}

EXTRACTED INFORMATION:
- Intent: {intent}
- Entities: {json.dumps(entities, indent=2)}

CRM VALIDATION:
{json.dumps(crm_validation, indent=2)}

FRAUD ASSESSMENT:
{json.dumps(fraud_score, indent=2)}

REFERENCE KNOWLEDGE BASE:
{rag_context}

YOUR TASK:
Generate a professional email response that:
1. Addresses the customer's inquiry based on the intent
2. References the knowledge base documents provided
3. Follows insurance compliance guidelines
4. Maintains accuracy and professionalism

REQUIRED OUTPUT FORMAT (JSON):
{{
    "response_text": "The complete email response text",
    "confidence_score": 0.0-1.0,
    "reference_ids": ["doc_id_1", "doc_id_2"],
    "compliance_checks": {{
        "contains_disclaimer": true/false,
        "factually_accurate": true/false,
        "references_policy": true/false
    }},
    "reasoning": "Brief explanation of your response"
}}

Provide ONLY the JSON response, no additional text."""

    return prompt


def invoke_claude(prompt: str) -> Dict[str, Any]:
    """
    Invoke Bedrock model with fallback support

    Tries primary model first, falls back to alternatives if needed

    Args:
        prompt: Input prompt

    Returns:
        Model response data
    """
    # Try primary model first
    models_to_try = [PRIMARY_MODEL_ID] + [m for m in FALLBACK_MODELS if m != PRIMARY_MODEL_ID]

    last_error = None
    for model_id in models_to_try:
        try:
            print(f"Trying model: {model_id}")
            response_body = invoke_bedrock_model(model_id, prompt)
            print(f"✓ Response received from {model_id}")
            return response_body

        except Exception as e:
            print(f"✗ Error with {model_id}: {str(e)}")
            last_error = e
            continue

    # All models failed
    raise Exception(f"All models failed. Last error: {str(last_error)}")


def invoke_bedrock_model(model_id: str, prompt: str) -> Dict[str, Any]:
    """
    Invoke specific Bedrock model with appropriate API format

    Args:
        model_id: Bedrock model ID
        prompt: Input prompt

    Returns:
        Model response data
    """
    try:
        # Determine model provider and format request accordingly
        if model_id.startswith('anthropic.'):
            # Claude models (Anthropic format)
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}]
            }

        elif model_id.startswith('meta.llama'):
            # Llama models (Meta format)
            request_body = {
                "prompt": prompt,
                "max_gen_len": 2000,
                "temperature": 0.1,
                "top_p": 0.9
            }

        elif model_id.startswith('mistral.'):
            # Mistral models (Mistral format)
            request_body = {
                "prompt": prompt,
                "max_tokens": 2000,
                "temperature": 0.1,
                "top_p": 0.9,
                "top_k": 50
            }

        elif model_id.startswith('amazon.titan'):
            # Titan models (Amazon format)
            request_body = {
                "inputText": prompt,
                "textGenerationConfig": {
                    "maxTokenCount": 2000,
                    "temperature": 0.1,
                    "topP": 0.9,
                    "stopSequences": []
                }
            }

        else:
            raise ValueError(f"Unsupported model: {model_id}")

        # Invoke model
        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            body=json.dumps(request_body),
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())

        # Normalize response format
        normalized = normalize_response(model_id, response_body)

        return normalized

    except Exception as e:
        print(f"Error invoking {model_id}: {str(e)}")
        raise


def normalize_response(model_id: str, response_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize different model response formats to a common structure

    Args:
        model_id: Model identifier
        response_body: Raw response from model

    Returns:
        Normalized response with 'content' field
    """
    if model_id.startswith('anthropic.'):
        # Claude format - already normalized
        return response_body

    elif model_id.startswith('meta.llama'):
        # Llama format
        return {
            'content': [{
                'text': response_body.get('generation', '')
            }],
            'usage': response_body.get('generation_token_count', {})
        }

    elif model_id.startswith('mistral.'):
        # Mistral format
        outputs = response_body.get('outputs', [])
        text = outputs[0].get('text', '') if outputs else ''
        return {
            'content': [{'text': text}],
            'usage': {}
        }

    elif model_id.startswith('amazon.titan'):
        # Titan format
        results = response_body.get('results', [])
        text = results[0].get('outputText', '') if results else ''
        return {
            'content': [{'text': text}],
            'usage': {}
        }

    else:
        # Unknown format - try to extract text field
        return {
            'content': [{'text': str(response_body)}],
            'usage': {}
        }


def parse_claude_response(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse Claude response and extract JSON

    Args:
        response_data: Raw response from Claude

    Returns:
        Parsed response dict
    """
    try:
        # Extract text content
        content = response_data.get('content', [])
        if not content:
            raise ValueError("Empty response from Claude")

        text = content[0].get('text', '')

        # Try to parse as JSON
        # Claude might wrap JSON in markdown code blocks
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0].strip()
        elif '```' in text:
            text = text.split('```')[1].split('```')[0].strip()

        parsed = json.loads(text)

        # Validate required fields
        if 'response_text' not in parsed or 'confidence_score' not in parsed:
            raise ValueError("Missing required fields in response")

        # Ensure confidence is in valid range
        confidence = float(parsed['confidence_score'])
        parsed['confidence_score'] = max(0.0, min(1.0, confidence))

        return parsed

    except json.JSONDecodeError as e:
        print(f"JSON parse error: {str(e)}")
        # Return default response
        return {
            'response_text': "We have received your email and will respond shortly.",
            'confidence_score': 0.3,
            'reference_ids': [],
            'compliance_checks': {},
            'reasoning': 'Failed to parse model response'
        }
    except Exception as e:
        print(f"Error parsing response: {str(e)}")
        return {
            'response_text': "We have received your email and will respond shortly.",
            'confidence_score': 0.3,
            'reference_ids': [],
            'compliance_checks': {},
            'reasoning': f'Error: {str(e)}'
        }


def build_evaluation_prompt(
    email_body: str,
    response_text: str,
    intent: str,
    rag_documents: List[Dict[str, Any]]
) -> str:
    """Build a task-type-aware evaluation prompt for the judge model."""
    intent_key = intent.lower().strip()
    criteria = TASK_TYPE_CRITERIA.get(intent_key)
    if not criteria:
        for key in TASK_TYPE_CRITERIA:
            if key in intent_key or intent_key in key:
                criteria = TASK_TYPE_CRITERIA[key]
                break
    if not criteria:
        criteria = TASK_TYPE_CRITERIA['inquiry']

    criteria_text = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(criteria))

    rag_context = "\n\n".join([
        f"[Reference {i+1}] {doc.get('content', '')[:300]}"
        for i, doc in enumerate(rag_documents[:3])
    ]) if rag_documents else "No reference documents."

    return f"""You are an expert insurance AI quality evaluator. Evaluate the accuracy and quality of the AI-generated response below.

CUSTOMER EMAIL:
{email_body}

DETECTED INTENT / TASK TYPE: {intent}

KNOWLEDGE BASE REFERENCES:
{rag_context}

AI-GENERATED RESPONSE TO EVALUATE:
{response_text}

TASK-SPECIFIC ACCURACY CRITERIA for "{intent}":
{criteria_text}

Score each dimension 0.0–1.0:
- accuracy_score: Factual accuracy given the knowledge base
- task_accuracy_score: Satisfies the task-specific criteria above
- compliance_score: Follows insurance compliance (disclaimers, no unverified guarantees)
- coherence_score: Clear, professional, well-structured
- overall_quality_score: Holistic quality

List any specific issues found.

REQUIRED OUTPUT (JSON only, no extra text):
{{
    "accuracy_score": 0.0,
    "task_accuracy_score": 0.0,
    "compliance_score": 0.0,
    "coherence_score": 0.0,
    "overall_quality_score": 0.0,
    "issues": [],
    "reasoning": "brief explanation"
}}"""


def evaluate_response(
    email_body: str,
    response_text: str,
    intent: str,
    rag_documents: List[Dict[str, Any]],
    primary_model_id: str
) -> Dict[str, Any]:
    """
    Invoke a separate evaluator model to score the generated response.

    Always uses a model different from the primary response model to provide
    an independent quality signal per task type.
    """
    evaluator_id = EVALUATOR_MODEL_ID
    # Guarantee evaluator != primary
    if evaluator_id == primary_model_id:
        evaluator_id = (
            'anthropic.claude-3-haiku-20240307-v1:0'
            if not primary_model_id.startswith('anthropic.')
            else 'mistral.mistral-7b-instruct-v0:2'
        )

    print(f"Evaluating response with {evaluator_id} (primary was {primary_model_id})")

    try:
        prompt = build_evaluation_prompt(email_body, response_text, intent, rag_documents)
        eval_start = datetime.utcnow()
        raw = invoke_bedrock_model(evaluator_id, prompt)
        eval_latency_ms = (datetime.utcnow() - eval_start).total_seconds() * 1000

        text = raw.get('content', [{}])[0].get('text', '{}')
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0].strip()
        elif '```' in text:
            text = text.split('```')[1].split('```')[0].strip()

        eval_result = json.loads(text)
        eval_result['evaluator_model'] = evaluator_id
        eval_result['eval_latency_ms'] = round(eval_latency_ms, 2)
        print(f"Evaluation complete — overall_quality={eval_result.get('overall_quality_score')}, "
              f"task_accuracy={eval_result.get('task_accuracy_score')}")
        return eval_result

    except Exception as e:
        print(f"Evaluation error: {e}")
        return {
            'accuracy_score': None,
            'task_accuracy_score': None,
            'compliance_score': None,
            'coherence_score': None,
            'overall_quality_score': None,
            'issues': [str(e)],
            'reasoning': 'Evaluation failed',
            'evaluator_model': evaluator_id,
            'eval_error': str(e)
        }


def update_email_record(email_id: str, result: Dict[str, Any], confidence_level: str) -> None:
    """Update email record in DynamoDB with response data and evaluation scores."""
    try:
        evaluation = result.get('evaluation', {})
        email_table.update_item(
            Key={'email_id': email_id},
            UpdateExpression=(
                'SET response_text = :text, confidence_score = :score, '
                'confidence_level = :level, processing_status = :status, '
                'action = :action, response_timestamp = :ts, '
                'eval_accuracy = :ea, eval_task_accuracy = :eta, '
                'eval_compliance = :ec, eval_overall = :eo, '
                'evaluator_model = :em'
            ),
            ExpressionAttributeValues={
                ':text': result['response_text'],
                ':score': str(result['confidence_score']),
                ':level': confidence_level,
                ':status': 'completed',
                ':action': result['action'],
                ':ts': result['timestamp'],
                ':ea': str(evaluation.get('accuracy_score', '')),
                ':eta': str(evaluation.get('task_accuracy_score', '')),
                ':ec': str(evaluation.get('compliance_score', '')),
                ':eo': str(evaluation.get('overall_quality_score', '')),
                ':em': evaluation.get('evaluator_model', ''),
            }
        )
        print(f"Updated email record: {email_id}")
    except Exception as e:
        print(f"Error updating DynamoDB: {str(e)}")
