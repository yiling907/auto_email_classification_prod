"""
Claude Response Generation Lambda Function
Generates high-confidence insurance email responses using Claude 3
"""
import json
import os
from typing import Dict, Any, List
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']

# Primary model for production responses — Claude 3 Sonnet as required by CLAUDE.md
PRIMARY_MODEL_ID = os.environ.get('PRIMARY_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')

# Fallback models tried in order if the primary model is unavailable
FALLBACK_MODELS = [
    'mistral.mistral-7b-instruct-v0:2',   # Mistral 7B: cheapest fallback
    'meta.llama3-8b-instruct-v1:0',       # Llama 3.1 8B: second fallback
]

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
    """
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

    raise Exception(f"All models failed. Last error: {str(last_error)}")


def invoke_bedrock_model(model_id: str, prompt: str) -> Dict[str, Any]:
    """Invoke specific Bedrock model with appropriate API format"""
    try:
        if model_id.startswith('anthropic.'):
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}]
            }
        elif model_id.startswith('meta.llama'):
            request_body = {
                "prompt": prompt,
                "max_gen_len": 2000,
                "temperature": 0.1,
                "top_p": 0.9
            }
        elif model_id.startswith('mistral.'):
            request_body = {
                "prompt": prompt,
                "max_tokens": 2000,
                "temperature": 0.1,
                "top_p": 0.9,
                "top_k": 50
            }
        elif model_id.startswith('amazon.titan'):
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

        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            body=json.dumps(request_body),
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())
        return normalize_response(model_id, response_body)

    except Exception as e:
        print(f"Error invoking {model_id}: {str(e)}")
        raise


def normalize_response(model_id: str, response_body: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize different model response formats to a common structure"""
    if model_id.startswith('anthropic.'):
        return response_body
    elif model_id.startswith('meta.llama'):
        return {
            'content': [{'text': response_body.get('generation', '')}],
            'usage': response_body.get('generation_token_count', {})
        }
    elif model_id.startswith('mistral.'):
        outputs = response_body.get('outputs', [])
        text = outputs[0].get('text', '') if outputs else ''
        return {'content': [{'text': text}], 'usage': {}}
    elif model_id.startswith('amazon.titan'):
        results = response_body.get('results', [])
        text = results[0].get('outputText', '') if results else ''
        return {'content': [{'text': text}], 'usage': {}}
    else:
        return {'content': [{'text': str(response_body)}], 'usage': {}}


def parse_claude_response(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Claude response and extract JSON"""
    try:
        content = response_data.get('content', [])
        if not content:
            raise ValueError("Empty response from Claude")

        text = content[0].get('text', '')

        if '```json' in text:
            text = text.split('```json')[1].split('```')[0].strip()
        elif '```' in text:
            text = text.split('```')[1].split('```')[0].strip()

        parsed = json.loads(text)

        if 'response_text' not in parsed or 'confidence_score' not in parsed:
            raise ValueError("Missing required fields in response")

        confidence = float(parsed['confidence_score'])
        parsed['confidence_score'] = max(0.0, min(1.0, confidence))

        return parsed

    except json.JSONDecodeError as e:
        print(f"JSON parse error: {str(e)}")
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


def update_email_record(email_id: str, result: Dict[str, Any], confidence_level: str) -> None:
    """Update email record in DynamoDB with response data."""
    try:
        email_table.update_item(
            Key={'email_id': email_id},
            UpdateExpression=(
                'SET response_text = :text, confidence_score = :score, '
                'confidence_level = :level, processing_status = :status, '
                '#action_attr = :action, response_timestamp = :ts'
            ),
            ExpressionAttributeNames={
                '#action_attr': 'action',  # 'action' is a DynamoDB reserved keyword
            },
            ExpressionAttributeValues={
                ':text': result['response_text'],
                ':score': str(result['confidence_score']),
                ':level': confidence_level,
                ':status': 'completed',
                ':action': result['action'],
                ':ts': result['timestamp'],
            }
        )
        print(f"Updated email record: {email_id}")
    except Exception as e:
        print(f"Error updating DynamoDB: {str(e)}")
