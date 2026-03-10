"""
Evaluation Metrics Lambda Function
Calculates performance metrics for model evaluation
"""
import json
import os
from typing import Dict, Any, List
from datetime import datetime, timedelta
import boto3

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')

# Environment variables
MODEL_METRICS_TABLE_NAME = os.environ['MODEL_METRICS_TABLE_NAME']
model_metrics_table = dynamodb.Table(MODEL_METRICS_TABLE_NAME)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for evaluation metrics

    Args:
        event: Contains task_type and optional time range
        context: Lambda context

    Returns:
        Dict with aggregated metrics
    """
    try:
        task_type = event.get('task_type', 'all')
        days = event.get('days', 7)

        print(f"Calculating metrics for task: {task_type}, last {days} days")

        # Query metrics from DynamoDB
        metrics = query_metrics(task_type, days)

        # Calculate aggregate statistics
        stats = calculate_statistics(metrics)

        return {
            'statusCode': 200,
            'task_type': task_type,
            'period_days': days,
            'statistics': stats,
            'sample_count': len(metrics)
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e)
        }


def query_metrics(task_type: str, days: int) -> List[Dict[str, Any]]:
    """
    Query metrics from DynamoDB

    Args:
        task_type: Task type to filter by
        days: Number of days to look back

    Returns:
        List of metric records
    """
    try:
        if task_type == 'all':
            # Scan all records (expensive - for demo only)
            response = model_metrics_table.scan()
        else:
            # Query by task_type
            response = model_metrics_table.query(
                KeyConditionExpression='task_type = :tt',
                ExpressionAttributeValues={
                    ':tt': task_type
                }
            )

        items = response.get('Items', [])

        # Filter by time window
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        filtered_items = [
            item for item in items
            if datetime.fromisoformat(item.get('timestamp', '').replace('Z', ''))
            > cutoff_date
        ]

        return filtered_items

    except Exception as e:
        print(f"Error querying metrics: {str(e)}")
        return []


def _avg(values: List[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def aggregate_laya_metrics(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate laya evaluation metrics written by run_local_evaluation.py.

    Reads fields: intent_accuracy, routing_accuracy, missed_escalation_rate,
    false_escalation_rate, extraction_record_accuracy from DynamoDB items
    with task_type == 'laya_eval'.

    Also aggregates Bedrock-eval LLM-as-judge scores:
    score_correctness, score_completeness, score_helpfulness, score_faithfulness.
    """
    laya_items = [i for i in items if i.get('task_type') == 'laya_eval']
    bedrock_items = [i for i in items if str(i.get('task_type', '')).startswith('bedrock_eval#')]

    def _collect(key: str, source: List[Dict]) -> List[float]:
        vals = []
        for i in source:
            v = i.get(key)
            if v is not None:
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    pass
        return vals

    laya_summary: Dict[str, Any] = {}
    if laya_items:
        laya_summary = {
            'sample_count': len(laya_items),
            'avg_intent_accuracy':           _avg(_collect('intent_accuracy', laya_items)),
            'avg_routing_accuracy':          _avg(_collect('routing_accuracy', laya_items)),
            'avg_missed_escalation_rate':    _avg(_collect('missed_escalation_rate', laya_items)),
            'avg_false_escalation_rate':     _avg(_collect('false_escalation_rate', laya_items)),
            'avg_extraction_record_accuracy':_avg(_collect('extraction_record_accuracy', laya_items)),
        }

    bedrock_summary: Dict[str, Any] = {}
    if bedrock_items:
        bedrock_summary = {
            'sample_count':           len(bedrock_items),
            'avg_score_correctness':  _avg(_collect('score_correctness', bedrock_items)),
            'avg_score_completeness': _avg(_collect('score_completeness', bedrock_items)),
            'avg_score_helpfulness':  _avg(_collect('score_helpfulness', bedrock_items)),
            'avg_score_faithfulness': _avg(_collect('score_faithfulness', bedrock_items)),
        }

    return {'laya_eval': laya_summary, 'bedrock_eval': bedrock_summary}


def calculate_statistics(metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate aggregate statistics from metrics

    Args:
        metrics: List of metric records

    Returns:
        Dict with statistics
    """
    if not metrics:
        return {
            'total_requests': 0,
            'success_rate': 0,
            'avg_latency_ms': 0,
            'total_cost_usd': 0
        }

    # Group by model
    by_model = {}
    for metric in metrics:
        model_name = metric.get('model_name', 'unknown')
        if model_name not in by_model:
            by_model[model_name] = []
        by_model[model_name].append(metric)

    # Calculate per-model stats
    model_stats = {}
    for model_name, model_metrics in by_model.items():
        successful = [m for m in model_metrics if m.get('success', False)]

        if model_metrics:
            latencies = [float(m.get('latency_ms', 0)) for m in successful]
            costs = [float(m.get('cost_usd', 0)) for m in successful]
            tokens_in = [int(m.get('input_tokens', 0)) for m in successful]
            tokens_out = [int(m.get('output_tokens', 0)) for m in successful]

            model_stats[model_name] = {
                'total_requests': len(model_metrics),
                'successful_requests': len(successful),
                'success_rate': len(successful) / len(model_metrics) if model_metrics else 0,
                'avg_latency_ms': sum(latencies) / len(latencies) if latencies else 0,
                'min_latency_ms': min(latencies) if latencies else 0,
                'max_latency_ms': max(latencies) if latencies else 0,
                'total_cost_usd': sum(costs),
                'avg_cost_usd': sum(costs) / len(costs) if costs else 0,
                'total_input_tokens': sum(tokens_in),
                'total_output_tokens': sum(tokens_out)
            }

    # Calculate overall stats
    all_latencies = [float(m.get('latency_ms', 0)) for m in metrics if m.get('success', False)]
    all_costs = [float(m.get('cost_usd', 0)) for m in metrics]
    successful_count = len([m for m in metrics if m.get('success', False)])

    # Aggregate laya + bedrock eval metrics
    laya_and_bedrock = aggregate_laya_metrics(metrics)

    overall_stats = {
        'total_requests': len(metrics),
        'successful_requests': successful_count,
        'success_rate': successful_count / len(metrics) if metrics else 0,
        'avg_latency_ms': sum(all_latencies) / len(all_latencies) if all_latencies else 0,
        'total_cost_usd': sum(all_costs),
        'by_model': model_stats,
        'laya_eval': laya_and_bedrock['laya_eval'],
        'bedrock_eval': laya_and_bedrock['bedrock_eval'],
    }

    return overall_stats
