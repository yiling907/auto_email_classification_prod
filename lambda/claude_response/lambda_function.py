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
CLAUDE_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

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
        intent = event.get('intent', 'unknown')
        rag_documents = event.get('rag_documents', [])
        crm_validation = event.get('crm_validation', {})
        fraud_score = event.get('fraud_score', {})

        if not email_body:
            raise ValueError("Missing email_body in event")

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
            'model_id': CLAUDE_MODEL_ID,
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
    Invoke Claude 3 model via Bedrock

    Args:
        prompt: Input prompt

    Returns:
        Model response data
    """
    try:
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "temperature": 0.1,  # Low temperature for consistency
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        response = bedrock_runtime.invoke_model(
            modelId=CLAUDE_MODEL_ID,
            body=json.dumps(request_body),
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())
        print(f"Claude response received")

        return response_body

    except Exception as e:
        print(f"Error invoking Claude: {str(e)}")
        raise


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


def update_email_record(email_id: str, result: Dict[str, Any], confidence_level: str) -> None:
    """Update email record in DynamoDB with response data"""
    try:
        email_table.update_item(
            Key={'email_id': email_id},
            UpdateExpression='SET response_text = :text, confidence_score = :score, '
                           'confidence_level = :level, processing_status = :status, '
                           'action = :action, response_timestamp = :ts',
            ExpressionAttributeValues={
                ':text': result['response_text'],
                ':score': result['confidence_score'],
                ':level': confidence_level,
                ':status': 'completed',
                ':action': result['action'],
                ':ts': result['timestamp']
            }
        )
        print(f"Updated email record: {email_id}")
    except Exception as e:
        print(f"Error updating DynamoDB: {str(e)}")
