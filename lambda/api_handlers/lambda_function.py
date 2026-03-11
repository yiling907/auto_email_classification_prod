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

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']
MODEL_METRICS_TABLE_NAME = os.environ['MODEL_METRICS_TABLE_NAME']
EMBEDDINGS_TABLE_NAME = os.environ['EMBEDDINGS_TABLE_NAME']

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
        elif path.startswith('/api/email/') and path.endswith('/send') and method == 'POST':
            email_id = path.split('/')[-2]
            response = send_email_response(email_id, event)
        elif path.startswith('/api/email/'):
            email_id = path.split('/')[-1]
            if method == 'POST':
                response = update_email_response_text(email_id, event)
            else:
                response = get_email_detail(email_id)
        elif path == '/api/metrics/models':
            response = get_model_metrics(event)
        elif path == '/api/metrics/rag':
            response = get_rag_metrics()
        elif path == '/api/settings' and method == 'GET':
            response = get_settings()
        elif path == '/api/settings' and method == 'POST':
            response = update_settings(event)
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
    """Get paginated list of emails with optional filters."""
    try:
        from boto3.dynamodb.conditions import Attr
        params = event.get('queryStringParameters') or {}
        limit             = int(params.get('limit', 50))
        confidence_level  = params.get('confidence_level')
        action_filter     = params.get('action')
        status_filter     = params.get('processing_status')

        # Build combined FilterExpression — boto3 Attr() handles reserved words internally
        filters = []
        if confidence_level:
            filters.append(Attr('confidence_level').eq(confidence_level))
        if action_filter:
            filters.append(Attr('action').eq(action_filter))
        if status_filter:
            filters.append(Attr('processing_status').eq(status_filter))

        scan_kwargs: Dict[str, Any] = {'Limit': limit}
        if filters:
            fe = filters[0]
            for f in filters[1:]:
                fe = fe & f
            scan_kwargs['FilterExpression'] = fe

        response = email_table.scan(**scan_kwargs)
        emails = response.get('Items', [])
        emails.sort(key=lambda x: x.get('received_at', ''), reverse=True)

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'emails': emails, 'count': len(emails)}, cls=DecimalEncoder),
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
    """Get model performance metrics grouped by task_type and model."""
    try:
        response = model_metrics_table.scan()
        records  = response.get('Items', [])

        # ── Group by task_type ─────────────────────────────────────────────────
        by_task: Dict[str, List] = {}
        for r in records:
            tt = r.get('task_type', 'unknown')
            by_task.setdefault(tt, []).append(r)

        task_stats: Dict[str, Any] = {}
        for tt, items in by_task.items():
            latencies = [float(m.get('latency_ms', 0)) for m in items]
            costs     = [float(m.get('cost_usd',   0)) for m in items]
            models    = list({m.get('model_name', 'unknown') for m in items})

            stat: Dict[str, Any] = {
                'models':        models,
                'count':         len(items),
                'avg_latency_ms': round(sum(latencies) / len(latencies), 2) if latencies else 0,
                'total_cost_usd': round(sum(costs), 6),
                'avg_cost_usd':   round(sum(costs) / len(costs), 6) if costs else 0,
            }

            # accuracy_evaluation — has overall_accuracy + per-field accuracy_scores
            if tt == 'accuracy_evaluation':
                acc_scores = [float(m['overall_accuracy']) for m in items if m.get('overall_accuracy')]
                stat['avg_overall_accuracy'] = round(sum(acc_scores) / len(acc_scores), 4) if acc_scores else 0
                # Per-field averages
                field_totals: Dict[str, List[float]] = {}
                for m in items:
                    for field, val in (m.get('accuracy_scores') or {}).items():
                        field_totals.setdefault(field, []).append(float(val))
                stat['avg_field_accuracy'] = {
                    f: round(sum(vs) / len(vs), 4) for f, vs in field_totals.items()
                }

            # response_evaluation — has confidence_score + per-dimension eval_scores
            if tt == 'response_evaluation':
                conf_scores = [float(m['confidence_score']) for m in items if m.get('confidence_score')]
                stat['avg_confidence_score'] = round(sum(conf_scores) / len(conf_scores), 4) if conf_scores else 0
                dim_totals: Dict[str, List[float]] = {}
                for m in items:
                    for dim, val in (m.get('eval_scores') or {}).items():
                        dim_totals.setdefault(dim, []).append(float(val))
                stat['avg_eval_scores'] = {
                    d: round(sum(vs) / len(vs), 4) for d, vs in dim_totals.items()
                }

            task_stats[tt] = stat

        # ── Aggregate by model_name ────────────────────────────────────────────
        by_model: Dict[str, Any] = {}
        for r in records:
            mn = r.get('model_name', 'unknown')
            if mn not in by_model:
                by_model[mn] = {'count': 0, 'total_cost_usd': 0.0, 'latencies': []}
            by_model[mn]['count']          += 1
            by_model[mn]['total_cost_usd'] += float(r.get('cost_usd', 0))
            by_model[mn]['latencies'].append(float(r.get('latency_ms', 0)))

        model_summary = {
            mn: {
                'count':          d['count'],
                'total_cost_usd': round(d['total_cost_usd'], 6),
                'avg_latency_ms': round(sum(d['latencies']) / len(d['latencies']), 2) if d['latencies'] else 0,
            }
            for mn, d in by_model.items()
        }

        # ── Recent records (sorted desc, last 50) ─────────────────────────────
        sorted_records = sorted(records, key=lambda x: x.get('timestamp', ''), reverse=True)[:50]

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'total_records': len(records),
                'by_task':       task_stats,
                'by_model':      model_summary,
                'records':       sorted_records,
            }, cls=DecimalEncoder),
        }

    except Exception as e:
        print(f"Error in get_model_metrics: {str(e)}")
        raise


def get_rag_metrics() -> Dict[str, Any]:
    """Get RAG effectiveness metrics — chunks, source files, and per-file chunk counts."""
    import re
    try:
        # Paginated scan — embeddings table has large items (vectors), hits 1 MB page limit
        documents = []
        scan_kwargs: Dict[str, Any] = {}
        while True:
            response = embeddings_table.scan(**scan_kwargs)
            documents.extend(response.get('Items', []))
            last = response.get('LastEvaluatedKey')
            if not last:
                break
            scan_kwargs['ExclusiveStartKey'] = last

        total_chunks = len(documents)

        # Derive source file name from doc_id pattern: <prefix>_<chunk_index>
        files_chunks: Dict[str, int] = {}
        for doc in documents:
            doc_id = doc.get('doc_id', '')
            m = re.match(r'^(.+)_(\d+)$', doc_id)
            source = m.group(1) if m else doc_id
            # Friendly display name: strip leading "documents_" or "knowledge_base_"
            display = re.sub(r'^(documents_|knowledge_base_)', '', source)
            files_chunks[display] = files_chunks.get(display, 0) + 1

        metrics = {
            'total_chunks':        total_chunks,
            'total_source_files':  len(files_chunks),
            'chunks_per_file':     files_chunks,
            'status': 'active' if total_chunks > 0 else 'empty',
        }

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(metrics, cls=DecimalEncoder),
        }

    except Exception as e:
        print(f"Error in get_rag_metrics: {str(e)}")
        raise


# ── Email response edit + send ────────────────────────────────────────────────

EMAIL_SENDER_FUNCTION = os.environ.get('EMAIL_SENDER_FUNCTION_NAME', 'insuremail-ai-dev-email-sender')


def update_email_response_text(email_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Persist an edited llm_response back to DynamoDB."""
    try:
        body = json.loads(event.get('body') or '{}')
        new_text = body.get('llm_response', '')
        if not new_text:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'llm_response is required'}),
            }
        email_table.update_item(
            Key={'email_id': email_id},
            UpdateExpression='SET llm_response = :r',
            ExpressionAttributeValues={':r': new_text},
        )
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'updated': True}),
        }
    except Exception as e:
        print(f"Error in update_email_response_text: {e}")
        raise


def send_email_response(email_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke the email_sender Lambda with the current (possibly edited) llm_response."""
    try:
        # Fetch fresh email record
        item = email_table.get_item(Key={'email_id': email_id}).get('Item')
        if not item:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Email not found'}),
            }

        payload = {
            'email_id':         email_id,
            'recipient_email':  item.get('sender_email', ''),
            'subject':          item.get('subject', ''),
            'response_text':    item.get('llm_response', ''),
            'confidence_score': float(item.get('confidence_score', 0)),
        }

        if not payload['recipient_email'] or not payload['response_text']:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Missing recipient_email or llm_response on email record'}),
            }

        result = LAMBDA_CLIENT.invoke(
            FunctionName=EMAIL_SENDER_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload).encode(),
        )
        sender_resp = json.loads(result['Payload'].read())
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'sent': True, 'sender_response': sender_resp}),
        }
    except Exception as e:
        print(f"Error in send_email_response: {e}")
        raise


# ── Settings (model toggle) ───────────────────────────────────────────────────

LAMBDA_CLIENT = boto3.client('lambda')

MANAGED_FUNCTIONS = {
    'classify_intent': os.environ.get('CLASSIFY_INTENT_FUNCTION_NAME', 'insuremail-ai-dev-multi-llm-inference'),
    'claude_response':  os.environ.get('CLAUDE_RESPONSE_FUNCTION_NAME', 'insuremail-ai-dev-claude-response'),
}

VALID_MODELS = {'mistral-7b', 'llama-3.1-8b'}


def _get_active_model(function_name: str) -> str:
    """Read ACTIVE_MODEL from a Lambda function's current environment."""
    cfg = LAMBDA_CLIENT.get_function_configuration(FunctionName=function_name)
    return cfg.get('Environment', {}).get('Variables', {}).get('ACTIVE_MODEL', 'mistral-7b')


def get_settings() -> Dict[str, Any]:
    """Return the current active model for each managed Lambda."""
    try:
        settings = {
            fn: _get_active_model(real_name)
            for fn, real_name in MANAGED_FUNCTIONS.items()
        }
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'settings': settings, 'valid_models': sorted(VALID_MODELS)}),
        }
    except Exception as e:
        print(f"Error in get_settings: {e}")
        raise


def update_settings(event: Dict[str, Any]) -> Dict[str, Any]:
    """Update ACTIVE_MODEL for one or both managed Lambdas.

    Body: {"classify_intent": "llama-3.1-8b", "claude_response": "mistral-7b"}
    Omit a key to leave that function unchanged.
    """
    try:
        body = json.loads(event.get('body') or '{}')
        updated = {}

        for fn, model in body.items():
            if fn not in MANAGED_FUNCTIONS:
                continue
            if model not in VALID_MODELS:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({'error': f"Invalid model '{model}'. Valid: {sorted(VALID_MODELS)}"}),
                }
            real_name = MANAGED_FUNCTIONS[fn]
            # Fetch current env vars and patch only ACTIVE_MODEL
            cfg = LAMBDA_CLIENT.get_function_configuration(FunctionName=real_name)
            env_vars = cfg.get('Environment', {}).get('Variables', {})
            env_vars['ACTIVE_MODEL'] = model
            LAMBDA_CLIENT.update_function_configuration(
                FunctionName=real_name,
                Environment={'Variables': env_vars},
            )
            updated[fn] = model
            print(f"Updated {real_name} ACTIVE_MODEL={model}")

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'updated': updated}),
        }
    except Exception as e:
        print(f"Error in update_settings: {e}")
        raise
