"""
Multi-LLM Inference Lambda Function
Runs multiple Bedrock models in parallel for benchmarking
"""
import json
import os
from typing import Dict, Any, List
from datetime import datetime
from decimal import Decimal
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.exceptions import ClientError

# Initialize AWS clients
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment variables
MODEL_METRICS_TABLE_NAME = os.environ['MODEL_METRICS_TABLE_NAME']
model_metrics_table = dynamodb.Table(MODEL_METRICS_TABLE_NAME)

# Valid output categories for email_classification task (laya dataset — 17 intents)
VALID_CATEGORIES = {
    'coverage_query', 'claim_submission', 'claim_status',
    'claim_reimbursement_query', 'pre_authorisation', 'payment_issue',
    'policy_change', 'renewal_query', 'cancellation_request',
    'enrollment_new_policy', 'dependent_addition', 'complaint',
    'document_followup', 'hospital_network_query', 'id_verification',
    'broker_query', 'other'
}

# Maps each intent to the appropriate handling team
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

# Model configurations - Working open source models only
MODELS = {
    'mistral-7b': {
        'id': 'mistral.mistral-7b-instruct-v0:2',
        'type': 'mistral',
        'cost_per_1k_input': 0.00015,
        'cost_per_1k_output': 0.00020
    },
    'llama-3.1-8b': {
        'id': 'meta.llama3-8b-instruct-v1:0',  # Using cross-region inference profile
        'type': 'meta',
        'cost_per_1k_input': 0.00030,
        'cost_per_1k_output': 0.00060
    }
    # Removed: titan-express (amazon.titan-text-express-v1 reached EOL)
}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for multi-LLM inference

    Args:
        event: Contains prompt and task_type
        context: Lambda context

    Returns:
        Dict with results from all models
    """
    try:
        prompt = event.get('prompt')
        task_type = event.get('task_type', 'intent_classification')

        if not prompt:
            raise ValueError("Missing prompt in event")

        print(f"Running multi-LLM inference for task: {task_type}")

        # Run all models in parallel
        results = run_parallel_inference(prompt, task_type)

        return {
            'statusCode': 200,
            'task_type': task_type,
            'results': results,
            'num_models': len(results)
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e),
            'results': []
        }


def run_parallel_inference(prompt: str, task_type: str) -> List[Dict[str, Any]]:
    """
    Run inference on multiple models in parallel

    Args:
        prompt: Input prompt
        task_type: Type of task (for metrics tracking)

    Returns:
        List of results from each model
    """
    results = []

    with ThreadPoolExecutor(max_workers=len(MODELS)) as executor:
        future_to_model = {
            executor.submit(invoke_model, model_name, model_config, prompt, task_type): model_name
            for model_name, model_config in MODELS.items()
        }

        for future in as_completed(future_to_model):
            model_name = future_to_model[future]
            try:
                result = future.result()
                results.append(result)
                print(f"Completed: {model_name}")
            except Exception as e:
                print(f"Error with {model_name}: {str(e)}")
                results.append({
                    'model_name': model_name,
                    'error': str(e),
                    'success': False
                })

    return results


def invoke_model(
    model_name: str,
    model_config: Dict[str, Any],
    prompt: str,
    task_type: str
) -> Dict[str, Any]:
    """
    Invoke a single model and collect metrics

    Args:
        model_name: Name of the model
        model_config: Model configuration
        prompt: Input prompt
        task_type: Task type

    Returns:
        Dict with model output and metrics
    """
    start_time = datetime.utcnow()

    try:
        model_id = model_config['id']
        model_type = model_config['type']

        # Build request based on model type
        if model_type == 'anthropic':
            # Claude models
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}]
            }
        elif model_type == 'meta':
            # Llama models
            request_body = {
                "prompt": prompt,
                "max_gen_len": 1000,
                "temperature": 0.1,
                "top_p": 0.9
            }
        elif model_type == 'mistral':
            # Mistral models
            request_body = {
                "prompt": prompt,
                "max_tokens": 1000,
                "temperature": 0.1,
                "top_p": 0.9,
                "top_k": 50
            }
        elif model_type == 'amazon':
            # Titan models
            request_body = {
                "inputText": prompt,
                "textGenerationConfig": {
                    "maxTokenCount": 1000,
                    "temperature": 0.1,
                    "topP": 0.9,
                    "stopSequences": []
                }
            }
        else:
            raise ValueError(f"Unsupported model type: {model_type}")

        # Invoke model
        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            body=json.dumps(request_body),
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())

        # Extract output based on model type
        if model_type == 'anthropic':
            # Claude format
            output_text = response_body.get('content', [{}])[0].get('text', '')
            usage = response_body.get('usage', {})
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)

        elif model_type == 'meta':
            # Llama format
            output_text = response_body.get('generation', '')
            input_tokens = response_body.get('prompt_token_count', 0)
            output_tokens = response_body.get('generation_token_count', 0)

        elif model_type == 'mistral':
            # Mistral format
            outputs = response_body.get('outputs', [])
            output_text = outputs[0].get('text', '') if outputs else ''
            # Mistral doesn't provide token counts, estimate (convert to int for DynamoDB)
            input_tokens = int(len(prompt.split()) * 1.3)
            output_tokens = int(len(output_text.split()) * 1.3)

        elif model_type == 'amazon':
            # Titan format
            results = response_body.get('results', [])
            output_text = results[0].get('outputText', '') if results else ''
            input_tokens = response_body.get('inputTextTokenCount', 0)
            output_tokens = results[0].get('tokenCount', 0) if results else int(len(output_text.split()) * 1.3)

        else:
            raise ValueError(f"Unsupported model type: {model_type}")

        # Calculate metrics
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        cost = calculate_cost(input_tokens, output_tokens, model_config)

        # Normalise output for email_classification task
        if task_type == 'email_classification':
            output_text = parse_classification_output(output_text)

        result = {
            'model_name': model_name,
            'model_id': model_id,
            'output_text': output_text,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'latency_ms': latency_ms,
            'cost_usd': cost,
            'success': True,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }

        # Store metrics
        store_metrics(task_type, model_name, result)

        return result

    except Exception as e:
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        print(f"Error invoking {model_name}: {str(e)}")
        return {
            'model_name': model_name,
            'error': str(e),
            'latency_ms': latency_ms,
            'success': False
        }


CLASSIFICATION_PROMPT_TEMPLATE = """You are an AI assistant for a health insurance company.
Classify the customer email below into exactly one of the following 17 intent categories:

coverage_query, claim_submission, claim_status, claim_reimbursement_query,
pre_authorisation, payment_issue, policy_change, renewal_query,
cancellation_request, enrollment_new_policy, dependent_addition, complaint,
document_followup, hospital_network_query, id_verification, broker_query, other

EMAIL:
{email_body}

Respond with ONLY a JSON object in this exact format (no other text):
{{"intent": "<one of the 17 categories>", "confidence": <0.0-1.0>, "route_team": "<team>"}}"""


def build_classification_prompt(email_body: str) -> str:
    """Build a classification prompt for the 17 laya intent categories."""
    return CLASSIFICATION_PROMPT_TEMPLATE.format(email_body=email_body)


def parse_classification_output(raw: str) -> str:
    """
    Normalise model output for the email_classification task.

    Tries JSON parsing first (expected format: {"intent": ..., "confidence": ..., "route_team": ...}).
    Falls back to string matching against VALID_CATEGORIES.
    Returns a JSON string with intent, confidence, and route_team on success,
    or a plain fallback category string.
    """
    import json as _json
    text = raw.strip()

    # Extract JSON if wrapped in markdown code fences
    if '```json' in text:
        text = text.split('```json')[1].split('```')[0].strip()
    elif '```' in text:
        text = text.split('```')[1].split('```')[0].strip()

    # Try JSON parse
    try:
        parsed = _json.loads(text)
        intent = parsed.get('intent', '').strip().lower()
        if intent in VALID_CATEGORIES:
            route_team = parsed.get('route_team') or INTENT_TO_ROUTE.get(intent, 'general_support_team')
            confidence = float(parsed.get('confidence', 0.7))
            return _json.dumps({
                'intent': intent,
                'confidence': round(confidence, 4),
                'route_team': route_team,
            })
    except (_json.JSONDecodeError, ValueError, TypeError):
        pass

    # Fallback: string matching
    candidate = text.strip('.,;:"\' \n').split('\n')[0].strip().lower()
    if candidate in VALID_CATEGORIES:
        route_team = INTENT_TO_ROUTE.get(candidate, 'general_support_team')
        return _json.dumps({'intent': candidate, 'confidence': 0.5, 'route_team': route_team})

    for category in VALID_CATEGORIES:
        if category in candidate:
            route_team = INTENT_TO_ROUTE.get(category, 'general_support_team')
            return _json.dumps({'intent': category, 'confidence': 0.4, 'route_team': route_team})

    print(f"Unrecognised classification output: {repr(raw)!r} – defaulting to other")
    return _json.dumps({'intent': 'other', 'confidence': 0.2, 'route_team': 'general_support_team'})


def calculate_cost(input_tokens: int, output_tokens: int, model_config: Dict[str, Any]) -> float:
    """Calculate cost in USD"""
    input_cost = (input_tokens / 1000) * model_config['cost_per_1k_input']
    output_cost = (output_tokens / 1000) * model_config['cost_per_1k_output']
    return round(input_cost + output_cost, 6)


def store_metrics(task_type: str, model_name: str, result: Dict[str, Any]) -> None:
    """Store model performance metrics in DynamoDB"""
    try:
        timestamp = datetime.utcnow().isoformat() + 'Z'
        model_timestamp = f"{model_name}#{timestamp}"

        # Convert numeric values to Decimal for DynamoDB compatibility
        item = {
            'task_type': task_type,
            'model_timestamp': model_timestamp,
            'model_name': model_name,
            'model_id': result.get('model_id'),
            'input_tokens': int(result.get('input_tokens', 0)),
            'output_tokens': int(result.get('output_tokens', 0)),
            'latency_ms': Decimal(str(result.get('latency_ms', 0))),
            'cost_usd': Decimal(str(result.get('cost_usd', 0))),
            'success': result.get('success', False),
            'timestamp': timestamp
        }

        model_metrics_table.put_item(Item=item)
        print(f"✓ Stored metrics for {model_name} ({task_type})")

    except Exception as e:
        print(f"✗ Error storing metrics for {model_name}: {str(e)}")
        # Re-raise to make failures visible
        raise
