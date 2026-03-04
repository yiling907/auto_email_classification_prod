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
            latencies = [m.get('latency_ms', 0) for m in successful]
            costs = [m.get('cost_usd', 0) for m in successful]
            tokens_in = [m.get('input_tokens', 0) for m in successful]
            tokens_out = [m.get('output_tokens', 0) for m in successful]

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
    all_latencies = [m.get('latency_ms', 0) for m in metrics if m.get('success', False)]
    all_costs = [m.get('cost_usd', 0) for m in metrics]
    successful_count = len([m for m in metrics if m.get('success', False)])

    overall_stats = {
        'total_requests': len(metrics),
        'successful_requests': successful_count,
        'success_rate': successful_count / len(metrics) if metrics else 0,
        'avg_latency_ms': sum(all_latencies) / len(all_latencies) if all_latencies else 0,
        'total_cost_usd': sum(all_costs),
        'by_model': model_stats
    }

    return overall_stats
