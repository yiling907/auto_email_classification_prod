"""
Bedrock Evaluation Lambda
Submits AWS Bedrock model evaluation jobs for all models (Mistral, Llama, Claude Haiku)
and a RAG simulation evaluation, then collects results into MODEL_METRICS_TABLE_NAME.

Two modes controlled by event.action:
  - 'submit'  : upload datasets → create evaluation jobs → store job records in DynamoDB
  - 'collect' : poll job status → read S3 results → aggregate + store scores in DynamoDB
"""
import json
import os
import re
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3

# AWS clients
bedrock = boto3.client('bedrock')
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Environment variables
MODEL_METRICS_TABLE_NAME = os.environ['MODEL_METRICS_TABLE_NAME']
KNOWLEDGE_BASE_BUCKET = os.environ['KNOWLEDGE_BASE_BUCKET']
LOGS_BUCKET = os.environ['LOGS_BUCKET']
BEDROCK_EVAL_ROLE_ARN = os.environ['BEDROCK_EVAL_ROLE_ARN']
AWS_ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID', '')
AWS_REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

model_metrics_table = dynamodb.Table(MODEL_METRICS_TABLE_NAME)

# Models to evaluate (subject models)
EVAL_MODELS = {
    'mistral-7b': 'mistral.mistral-7b-instruct-v0:2',
    'llama-3-8b': 'meta.llama3-8b-instruct-v1:0',
    'claude-haiku': 'anthropic.claude-3-haiku-20240307-v1:0',
}

# Claude Haiku is the LLM-as-judge evaluator for all jobs
JUDGE_MODEL = 'anthropic.claude-3-haiku-20240307-v1:0'

# S3 paths
DATASET_PREFIX = 'eval-datasets/'
RESULTS_PREFIX = 'bedrock-eval-results/'

# Dataset local paths (relative to Lambda package root)
DATASETS = {
    'model_eval': 'insurance_model_eval.jsonl',
    'rag_eval': 'insurance_rag_eval.jsonl',
}

# Metrics to request from Bedrock for each job
MODEL_EVAL_METRICS = [
    'Builtin.Correctness',
    'Builtin.Completeness',
    'Builtin.Helpfulness',
]

RAG_EVAL_METRICS = [
    'Builtin.Faithfulness',
    'Builtin.Correctness',
    'Builtin.Completeness',
]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    action = event.get('action', 'submit')

    if action == 'submit':
        return submit_all_jobs(event)
    elif action == 'collect':
        return collect_all_results(event)
    else:
        return {'statusCode': 400, 'error': f"Unknown action: {action}. Use 'submit' or 'collect'."}


# ---------------------------------------------------------------------------
# SUBMIT
# ---------------------------------------------------------------------------

def submit_all_jobs(event: Dict[str, Any]) -> Dict[str, Any]:
    """Upload datasets and submit one Bedrock evaluation job per model + RAG."""
    print("Uploading evaluation datasets to S3...")
    upload_datasets()

    model_dataset_uri = f"s3://{KNOWLEDGE_BASE_BUCKET}/{DATASET_PREFIX}insurance_model_eval.jsonl"
    rag_dataset_uri = f"s3://{KNOWLEDGE_BASE_BUCKET}/{DATASET_PREFIX}insurance_rag_eval.jsonl"
    output_uri = f"s3://{LOGS_BUCKET}/{RESULTS_PREFIX}"

    submitted_jobs = []

    # --- Model evaluation jobs (one per subject model) ---
    for model_name, model_id in EVAL_MODELS.items():
        try:
            job_arn = submit_model_eval_job(
                model_name=model_name,
                model_id=model_id,
                dataset_uri=model_dataset_uri,
                output_uri=output_uri,
            )
            record = store_job_record(
                task_type='bedrock_eval#model_qa',
                model_name=model_name,
                model_id=model_id,
                job_arn=job_arn,
                eval_type='model_evaluation',
            )
            submitted_jobs.append(record)
            print(f"✓ Submitted model eval for {model_name}: {job_arn}")
        except Exception as e:
            print(f"✗ Failed to submit eval for {model_name}: {e}")
            submitted_jobs.append({'model_name': model_name, 'error': str(e)})

    # --- RAG simulation evaluation (Claude Haiku evaluates RAG-style QA quality) ---
    # Uses a dataset where prompts include retrieved context — evaluates how faithfully
    # each model uses grounded context. We submit one job per model for consistency.
    for model_name, model_id in EVAL_MODELS.items():
        try:
            job_arn = submit_rag_eval_job(
                model_name=model_name,
                model_id=model_id,
                dataset_uri=rag_dataset_uri,
                output_uri=output_uri,
            )
            record = store_job_record(
                task_type='bedrock_eval#rag_qa',
                model_name=model_name,
                model_id=model_id,
                job_arn=job_arn,
                eval_type='rag_evaluation',
            )
            submitted_jobs.append(record)
            print(f"✓ Submitted RAG eval for {model_name}: {job_arn}")
        except Exception as e:
            print(f"✗ Failed to submit RAG eval for {model_name}: {e}")
            submitted_jobs.append({'model_name': model_name, 'error': str(e)})

    return {
        'statusCode': 200,
        'jobs_submitted': len([j for j in submitted_jobs if 'job_arn' in j]),
        'jobs': submitted_jobs,
    }


def submit_model_eval_job(
    model_name: str,
    model_id: str,
    dataset_uri: str,
    output_uri: str,
) -> str:
    """Submit a Bedrock automated model evaluation job. Returns the job ARN."""
    ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    # Job names: lowercase alphanumeric + hyphens, max 63 chars
    safe_name = re.sub(r'[^a-z0-9-]', '-', model_name.lower())
    job_name = f"insuremail-{safe_name}-qa-{ts}"[:63]

    model_arn = f"arn:aws:bedrock:{AWS_REGION}::foundation-model/{model_id}"

    response = bedrock.create_evaluation_job(
        jobName=job_name,
        jobDescription=f"Insurance QA evaluation for {model_name}",
        roleArn=BEDROCK_EVAL_ROLE_ARN,
        applicationType='ModelEvaluation',
        inferenceConfig={
            'models': [
                {
                    'bedrockModel': {
                        'modelIdentifier': model_arn,
                        'inferenceParams': json.dumps({
                            'inferenceConfig': {
                                'maxTokens': 512,
                                'temperature': 0.0,
                                'topP': 1.0,
                            }
                        }),
                    }
                }
            ]
        },
        outputDataConfig={'s3Uri': output_uri},
        evaluationConfig={
            'automated': {
                'datasetMetricConfigs': [
                    {
                        'taskType': 'General',
                        'dataset': {
                            'name': 'InsuranceQA',
                            'datasetLocation': {'s3Uri': dataset_uri},
                        },
                        'metricNames': MODEL_EVAL_METRICS,
                    }
                ],
                'evaluatorModelConfig': {
                    'bedrockEvaluatorModels': [
                        {'modelIdentifier': JUDGE_MODEL}
                    ]
                },
            }
        },
    )
    return response['jobArn']


def submit_rag_eval_job(
    model_name: str,
    model_id: str,
    dataset_uri: str,
    output_uri: str,
) -> str:
    """Submit a RAG-simulation evaluation job (context-grounded QA). Returns the job ARN."""
    ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    safe_name = re.sub(r'[^a-z0-9-]', '-', model_name.lower())
    job_name = f"insuremail-{safe_name}-rag-{ts}"[:63]

    model_arn = f"arn:aws:bedrock:{AWS_REGION}::foundation-model/{model_id}"

    response = bedrock.create_evaluation_job(
        jobName=job_name,
        jobDescription=f"RAG faithfulness evaluation for {model_name}",
        roleArn=BEDROCK_EVAL_ROLE_ARN,
        applicationType='ModelEvaluation',
        inferenceConfig={
            'models': [
                {
                    'bedrockModel': {
                        'modelIdentifier': model_arn,
                        'inferenceParams': json.dumps({
                            'inferenceConfig': {
                                'maxTokens': 512,
                                'temperature': 0.0,
                                'topP': 1.0,
                            }
                        }),
                    }
                }
            ]
        },
        outputDataConfig={'s3Uri': output_uri},
        evaluationConfig={
            'automated': {
                'datasetMetricConfigs': [
                    {
                        'taskType': 'General',
                        'dataset': {
                            'name': 'InsuranceRAGSimulation',
                            'datasetLocation': {'s3Uri': dataset_uri},
                        },
                        'metricNames': RAG_EVAL_METRICS,
                    }
                ],
                'evaluatorModelConfig': {
                    'bedrockEvaluatorModels': [
                        {'modelIdentifier': JUDGE_MODEL}
                    ]
                },
            }
        },
    )
    return response['jobArn']


# ---------------------------------------------------------------------------
# COLLECT
# ---------------------------------------------------------------------------

def collect_all_results(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Poll all InProgress Bedrock eval jobs stored in DynamoDB.
    For completed jobs, read S3 results and store aggregate scores back into DynamoDB.
    """
    # Scan for InProgress jobs
    response = model_metrics_table.scan(
        FilterExpression='attribute_exists(job_arn) AND eval_status = :s',
        ExpressionAttributeValues={':s': 'InProgress'},
    )
    jobs = response.get('Items', [])
    print(f"Found {len(jobs)} InProgress Bedrock eval jobs")

    updated = []
    for job in jobs:
        job_arn = job.get('job_arn')
        model_name = job.get('model_name')
        task_type = job.get('task_type')
        try:
            result = process_job(job_arn, model_name, task_type, job)
            updated.append(result)
        except Exception as e:
            print(f"✗ Error processing {job_arn}: {e}")
            updated.append({'job_arn': job_arn, 'error': str(e)})

    return {
        'statusCode': 200,
        'jobs_checked': len(jobs),
        'jobs_updated': len([u for u in updated if u.get('status') == 'Completed']),
        'results': updated,
    }


def process_job(
    job_arn: str,
    model_name: str,
    task_type: str,
    db_item: Dict[str, Any],
) -> Dict[str, Any]:
    """Check one job's status; if complete, read S3 and update DynamoDB."""
    job_info = bedrock.get_evaluation_job(jobIdentifier=job_arn)
    status = job_info['status']
    print(f"Job {job_arn} status: {status}")

    if status == 'Completed':
        output_uri = job_info['outputDataConfig']['s3Uri']
        scores = read_scores_from_s3(output_uri, job_arn)
        update_job_record(db_item, status='Completed', scores=scores)
        return {'job_arn': job_arn, 'model_name': model_name, 'status': 'Completed', 'scores': scores}

    elif status == 'Failed':
        failures = job_info.get('failureMessages', [])
        update_job_record(db_item, status='Failed', scores={}, failure_messages=failures)
        return {'job_arn': job_arn, 'model_name': model_name, 'status': 'Failed', 'failures': failures}

    else:
        # Still running
        return {'job_arn': job_arn, 'model_name': model_name, 'status': status}


def read_scores_from_s3(output_s3_uri: str, job_arn: str) -> Dict[str, Any]:
    """
    Walk the Bedrock eval output prefix and compute average scores from all _output.jsonl files.
    Returns a dict of metric_name → average_score.
    """
    bucket, prefix = output_s3_uri.replace('s3://', '').split('/', 1)
    # Bedrock writes results under {prefix}{job-name}/{uuid}/...
    # List everything under the prefix to find output files
    paginator = s3.get_paginator('list_objects_v2')
    output_files = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('_output.jsonl'):
                output_files.append(obj['Key'])

    if not output_files:
        print(f"No output files found under {output_s3_uri}")
        return {}

    metric_values: Dict[str, List[float]] = {}
    for key in output_files:
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            lines = obj['Body'].read().decode('utf-8').strip().split('\n')
            for line in lines:
                if not line:
                    continue
                record = json.loads(line)
                eval_result = record.get('automatedEvaluationResult', {})
                for score in eval_result.get('scores', []):
                    metric = score.get('metricName', '').replace('Builtin.', '')
                    value = score.get('result')
                    if value is not None:
                        metric_values.setdefault(metric, []).append(float(value))
        except Exception as e:
            print(f"Error reading {key}: {e}")

    # Average each metric
    return {
        metric: round(sum(vals) / len(vals), 4)
        for metric, vals in metric_values.items()
        if vals
    }


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def store_job_record(
    task_type: str,
    model_name: str,
    model_id: str,
    job_arn: str,
    eval_type: str,
) -> Dict[str, Any]:
    """Write a new eval job record to MODEL_METRICS_TABLE_NAME with status=InProgress."""
    timestamp = datetime.utcnow().isoformat() + 'Z'
    item = {
        'task_type': task_type,
        'model_timestamp': f"{model_name}#{timestamp}",
        'model_name': model_name,
        'model_id': model_id,
        'job_arn': job_arn,
        'eval_type': eval_type,
        'eval_status': 'InProgress',
        'judge_model': JUDGE_MODEL,
        'timestamp': timestamp,
        'success': False,  # updated to True when Completed
    }
    model_metrics_table.put_item(Item=item)
    return item


def update_job_record(
    db_item: Dict[str, Any],
    status: str,
    scores: Dict[str, Any],
    failure_messages: Optional[List[str]] = None,
) -> None:
    """Update an eval job record in DynamoDB with final status and scores."""
    timestamp = datetime.utcnow().isoformat() + 'Z'
    update_expr_parts = [
        'eval_status = :status',
        'collected_timestamp = :ts',
        'success = :ok',
    ]
    expr_values: Dict[str, Any] = {
        ':status': status,
        ':ts': timestamp,
        ':ok': status == 'Completed',
    }

    # Store each metric score
    for metric, value in scores.items():
        safe_key = re.sub(r'[^a-zA-Z0-9_]', '_', metric).lower()
        attr = f"score_{safe_key}"
        update_expr_parts.append(f"{attr} = :{safe_key}")
        expr_values[f":{safe_key}"] = Decimal(str(value))

    if failure_messages:
        update_expr_parts.append('failure_messages = :fm')
        expr_values[':fm'] = failure_messages

    model_metrics_table.update_item(
        Key={
            'task_type': db_item['task_type'],
            'model_timestamp': db_item['model_timestamp'],
        },
        UpdateExpression='SET ' + ', '.join(update_expr_parts),
        ExpressionAttributeValues=expr_values,
    )
    print(f"✓ Updated record for {db_item['model_name']} → {status} | scores={scores}")


# ---------------------------------------------------------------------------
# Dataset upload
# ---------------------------------------------------------------------------

def upload_datasets() -> None:
    """Upload evaluation datasets from the Lambda package to S3."""
    base_dir = os.path.dirname(__file__)
    for local_name in DATASETS.values():
        local_path = os.path.join(base_dir, local_name)
        s3_key = f"{DATASET_PREFIX}{local_name}"
        try:
            s3.upload_file(local_path, KNOWLEDGE_BASE_BUCKET, s3_key)
            print(f"✓ Uploaded {local_name} → s3://{KNOWLEDGE_BASE_BUCKET}/{s3_key}")
        except Exception as e:
            print(f"✗ Failed to upload {local_name}: {e}")
            raise
