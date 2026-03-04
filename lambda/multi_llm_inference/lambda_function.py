"""
Multi-LLM Inference Lambda Function
Runs multiple Bedrock models in parallel for benchmarking
"""
import json
import os
from typing import Dict, Any, List
from datetime import datetime
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.exceptions import ClientError

# Initialize AWS clients
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Environment variables
MODEL_METRICS_TABLE_NAME = os.environ['MODEL_METRICS_TABLE_NAME']
model_metrics_table = dynamodb.Table(MODEL_METRICS_TABLE_NAME)

# Model configurations - Open source models only
MODELS = {
    'llama-3.1-8b': {
        'id': 'meta.llama3-1-8b-instruct-v1:0',
        'type': 'meta',
        'cost_per_1k_input': 0.00030,
        'cost_per_1k_output': 0.00060
    },
    'mistral-7b': {
        'id': 'mistral.mistral-7b-instruct-v0:2',
        'type': 'mistral',
        'cost_per_1k_input': 0.00015,
        'cost_per_1k_output': 0.00020
    },
    'titan-express': {
        'id': 'amazon.titan-text-express-v1',
        'type': 'amazon',
        'cost_per_1k_input': 0.00020,
        'cost_per_1k_output': 0.00060
    }
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
            # Mistral doesn't provide token counts, estimate
            input_tokens = len(prompt.split()) * 1.3
            output_tokens = len(output_text.split()) * 1.3

        elif model_type == 'amazon':
            # Titan format
            results = response_body.get('results', [])
            output_text = results[0].get('outputText', '') if results else ''
            input_tokens = response_body.get('inputTextTokenCount', 0)
            output_tokens = results[0].get('tokenCount', 0) if results else len(output_text.split()) * 1.3

        else:
            raise ValueError(f"Unsupported model type: {model_type}")

        # Calculate metrics
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        cost = calculate_cost(input_tokens, output_tokens, model_config)

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

        item = {
            'task_type': task_type,
            'model_timestamp': model_timestamp,
            'model_name': model_name,
            'model_id': result.get('model_id'),
            'input_tokens': result.get('input_tokens', 0),
            'output_tokens': result.get('output_tokens', 0),
            'latency_ms': result.get('latency_ms', 0),
            'cost_usd': result.get('cost_usd', 0),
            'success': result.get('success', False),
            'timestamp': timestamp
        }

        model_metrics_table.put_item(Item=item)

    except Exception as e:
        print(f"Error storing metrics: {str(e)}")
