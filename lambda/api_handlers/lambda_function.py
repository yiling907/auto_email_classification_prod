"""
API Handler Lambda Function
Provides REST API endpoints for dashboard
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

# Environment variables
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']
MODEL_METRICS_TABLE_NAME = os.environ['MODEL_METRICS_TABLE_NAME']
EMBEDDINGS_TABLE_NAME = os.environ['EMBEDDINGS_TABLE_NAME']
EVALUATION_METRICS_FUNCTION_NAME = os.environ.get('EVALUATION_METRICS_FUNCTION_NAME', '')

email_table = dynamodb.Table(EMAIL_TABLE_NAME)
model_metrics_table = dynamodb.Table(MODEL_METRICS_TABLE_NAME)
embeddings_table = dynamodb.Table(EMBEDDINGS_TABLE_NAME)


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main API Gateway handler
    Routes requests based on path and method
    """
    try:
        path = event.get('path', '')
        method = event.get('httpMethod', 'GET')

        print(f"Request: {method} {path}")

        # Route to appropriate handler
        if path == '/api/dashboard/overview':
            response = get_dashboard_overview()
        elif path == '/api/emails':
            response = get_emails_list(event)
        elif path.startswith('/api/email/'):
            email_id = path.split('/')[-1]
            response = get_email_detail(email_id)
        elif path == '/api/metrics/models':
            response = get_model_metrics(event)
        elif path == '/api/metrics/rag':
            response = get_rag_metrics()
        else:
            response = {
                'statusCode': 404,
                'body': json.dumps({'error': 'Not found'})
            }

        # Add CORS headers
        if 'headers' not in response:
            response['headers'] = {}
        response['headers'].update({
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
        })

        return response

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Content-Type': 'application/json'
            },
            'body': json.dumps({'error': str(e)})
        }


def get_dashboard_overview() -> Dict[str, Any]:
    """Get overview statistics for dashboard"""
    try:
        # Get email statistics
        email_response = email_table.scan()
        emails = email_response.get('Items', [])

        total_emails = len(emails)

        # Count by confidence level
        confidence_counts = {
            'high': 0,
            'medium': 0,
            'low': 0,
            'pending': 0
        }

        for email in emails:
            level = email.get('confidence_level', 'pending')
            confidence_counts[level] = confidence_counts.get(level, 0) + 1

        # Calculate average confidence
        scores = [float(e.get('confidence_score', 0)) for e in emails if e.get('confidence_score')]
        avg_confidence = sum(scores) / len(scores) if scores else 0

        # Count auto-responses
        auto_responses = len([e for e in emails if e.get('action') == 'auto_response'])
        auto_response_rate = (auto_responses / total_emails * 100) if total_emails > 0 else 0

        # Get recent emails
        recent_emails = sorted(emails, key=lambda x: x.get('timestamp', ''), reverse=True)[:10]

        overview = {
            'total_emails': total_emails,
            'avg_confidence': round(avg_confidence, 2),
            'auto_response_rate': round(auto_response_rate, 1),
            'confidence_distribution': confidence_counts,
            'recent_emails': [
                {
                    'email_id': e.get('email_id'),
                    'subject': e.get('subject', 'No subject'),
                    'timestamp': e.get('timestamp'),
                    'confidence_level': e.get('confidence_level'),
                    'action': e.get('action', 'pending')
                }
                for e in recent_emails
            ]
        }

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(overview, cls=DecimalEncoder)
        }

    except Exception as e:
        print(f"Error in get_dashboard_overview: {str(e)}")
        raise


def get_emails_list(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get paginated list of emails"""
    try:
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        limit = int(params.get('limit', 50))
        confidence_level = params.get('confidence_level')

        # Scan emails
        scan_kwargs = {'Limit': limit}

        if confidence_level:
            # Use GSI to query by confidence level
            response = email_table.query(
                IndexName='timestamp-index',
                KeyConditionExpression=Key('confidence_level').eq(confidence_level),
                Limit=limit,
                ScanIndexForward=False
            )
        else:
            response = email_table.scan(**scan_kwargs)

        emails = response.get('Items', [])

        # Sort by timestamp
        emails.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'emails': emails,
                'count': len(emails)
            }, cls=DecimalEncoder)
        }

    except Exception as e:
        print(f"Error in get_emails_list: {str(e)}")
        raise


def get_email_detail(email_id: str) -> Dict[str, Any]:
    """Get detailed information for a specific email"""
    try:
        response = email_table.get_item(Key={'email_id': email_id})
        email = response.get('Item')

        if not email:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Email not found'})
            }

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(email, cls=DecimalEncoder)
        }

    except Exception as e:
        print(f"Error in get_email_detail: {str(e)}")
        raise


def get_model_metrics(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get model performance metrics - delegates to evaluation_metrics Lambda"""
    try:
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        task_type = params.get('task_type', 'all')
        days = int(params.get('days', 7))

        # Call evaluation_metrics Lambda if configured
        if EVALUATION_METRICS_FUNCTION_NAME:
            try:
                response = lambda_client.invoke(
                    FunctionName=EVALUATION_METRICS_FUNCTION_NAME,
                    InvocationType='RequestResponse',
                    Payload=json.dumps({
                        'task_type': task_type,
                        'days': days
                    })
                )

                payload = json.loads(response['Payload'].read())

                if payload.get('statusCode') == 200:
                    # Extract statistics from evaluation_metrics response
                    # and return in the format expected by frontend
                    stats = payload.get('statistics', {})
                    return {
                        'statusCode': 200,
                        'headers': {'Content-Type': 'application/json'},
                        'body': json.dumps({
                            'by_model': stats.get('by_model', {}),
                            'total_metrics': stats.get('total_requests', 0)
                        }, cls=DecimalEncoder)
                    }

            except Exception as e:
                print(f"Error calling evaluation_metrics Lambda: {str(e)}")
                # Fall back to direct calculation below

        # Fallback: Direct calculation (for backward compatibility)
        response = model_metrics_table.scan()
        metrics = response.get('Items', [])

        # Group by model
        by_model = {}
        for metric in metrics:
            model_name = metric.get('model_name', 'unknown')
            if model_name not in by_model:
                by_model[model_name] = []
            by_model[model_name].append(metric)

        # Calculate aggregate stats
        model_stats = {}
        for model_name, model_metrics in by_model.items():
            successful = [m for m in model_metrics if m.get('success')]

            if model_metrics:
                latencies = [float(m.get('latency_ms', 0)) for m in successful]
                costs = [float(m.get('cost_usd', 0)) for m in successful]

                model_stats[model_name] = {
                    'total_requests': len(model_metrics),
                    'successful_requests': len(successful),
                    'success_rate': round(len(successful) / len(model_metrics) * 100, 1),
                    'avg_latency_ms': round(sum(latencies) / len(latencies), 2) if latencies else 0,
                    'total_cost_usd': round(sum(costs), 4),
                    'avg_cost_usd': round(sum(costs) / len(costs), 6) if costs else 0
                }

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'by_model': model_stats,
                'total_metrics': len(metrics)
            }, cls=DecimalEncoder)
        }

    except Exception as e:
        print(f"Error in get_model_metrics: {str(e)}")
        raise


def get_rag_metrics() -> Dict[str, Any]:
    """Get RAG effectiveness metrics"""
    try:
        # Get embeddings count
        response = embeddings_table.scan(Select='COUNT')
        total_documents = response.get('Count', 0)

        # Get document types distribution
        doc_response = embeddings_table.scan()
        documents = doc_response.get('Items', [])

        doc_types = {}
        for doc in documents:
            doc_type = doc.get('doc_type', 'unknown')
            doc_types[doc_type] = doc_types.get(doc_type, 0) + 1

        metrics = {
            'total_documents': total_documents,
            'by_type': doc_types,
            'status': 'active' if total_documents > 0 else 'empty'
        }

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(metrics, cls=DecimalEncoder)
        }

    except Exception as e:
        print(f"Error in get_rag_metrics: {str(e)}")
        raise
