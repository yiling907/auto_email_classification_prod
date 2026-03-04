# Evaluation Metrics Integration

## Overview

The `evaluation_metrics` Lambda function is now **fully integrated** into the InsureMail AI system. It provides centralized model performance analytics and is triggered both automatically and on-demand.

---

## Integration Points

### 1. **Scheduled Automatic Execution** (EventBridge/CloudWatch Events)

The evaluation_metrics Lambda runs automatically on a schedule:

**Daily Metrics** (9:00 AM UTC):
- Calculates performance metrics for the last 7 days
- Aggregates model performance stats
- Event payload:
  ```json
  {
    "task_type": "all",
    "days": 7
  }
  ```

**Weekly Reports** (Sunday 00:00 UTC):
- Comprehensive 30-day metrics report
- Detailed model comparison
- Event payload:
  ```json
  {
    "task_type": "all",
    "days": 30
  }
  ```

### 2. **API Integration** (Dashboard Queries)

The `api_handlers` Lambda now delegates to `evaluation_metrics` for model metrics:

**Endpoint**: `GET /api/metrics/models`

**Query Parameters**:
- `task_type` (default: "all") - Filter by task type
- `days` (default: 7) - Time window in days

**Example Request**:
```bash
curl "https://your-api-gateway-url/api/metrics/models?task_type=intent_classification&days=14"
```

**Flow**:
```
API Gateway
  → api_handlers Lambda
    → evaluation_metrics Lambda (invoked)
      → MODEL_METRICS_TABLE (query)
    ← Statistics & aggregations
  ← JSON response
```

**Fallback**: If evaluation_metrics Lambda is unavailable, api_handlers falls back to direct DynamoDB queries for backward compatibility.

### 3. **Manual Invocation** (CLI/Testing)

You can invoke the Lambda manually for ad-hoc analysis:

```bash
# Get last 7 days of metrics
aws lambda invoke \
  --function-name insuremail-ai-dev-evaluation-metrics \
  --payload '{"task_type":"all","days":7}' \
  response.json

# Get specific task metrics
aws lambda invoke \
  --function-name insuremail-ai-dev-evaluation-metrics \
  --payload '{"task_type":"intent_classification","days":30}' \
  response.json

# View results
cat response.json | jq '.'
```

---

## Data Flow

```
Multi-LLM Inference
  ↓
MODEL_METRICS_TABLE
  (stores raw metrics per invocation)
  ↓
evaluation_metrics Lambda
  (aggregates & calculates statistics)
  ↓
  - EventBridge Schedule (automatic)
  - API Handler (on-demand)
  - Manual Invocation (testing)
  ↓
Dashboard / Reports
```

---

## Metrics Calculated

The evaluation_metrics Lambda calculates:

### Overall Statistics
- `total_requests`: Total number of model invocations
- `successful_requests`: Count of successful invocations
- `success_rate`: Percentage of successful invocations
- `avg_latency_ms`: Average response time
- `total_cost_usd`: Cumulative cost

### Per-Model Statistics
- `total_requests`: Requests to this specific model
- `successful_requests`: Successful invocations
- `success_rate`: Model-specific success rate
- `avg_latency_ms`: Average latency for this model
- `min_latency_ms`: Fastest response time
- `max_latency_ms`: Slowest response time
- `total_cost_usd`: Total cost for this model
- `avg_cost_usd`: Average cost per invocation
- `total_input_tokens`: Sum of all input tokens
- `total_output_tokens`: Sum of all output tokens

---

## Configuration

### Terraform Resources

**EventBridge Rules**: `terraform/modules/monitoring/eventbridge.tf`
```hcl
resource "aws_cloudwatch_event_rule" "daily_metrics"
resource "aws_cloudwatch_event_target" "evaluation_metrics"
resource "aws_lambda_permission" "allow_eventbridge_daily_metrics"
```

**Lambda Environment Variables** (api_handlers):
```hcl
EVALUATION_METRICS_FUNCTION_NAME = aws_lambda_function.evaluation_metrics.function_name
```

**IAM Permissions**:
```hcl
resource "aws_iam_role_policy" "lambda_invoke"
# Allows api_handlers to invoke evaluation_metrics
```

---

## Deployment

Deploy the integration:

```bash
cd terraform
terraform plan
terraform apply
```

This will:
1. ✅ Create EventBridge rules for scheduled execution
2. ✅ Grant Lambda invocation permissions
3. ✅ Configure api_handlers with evaluation_metrics function name
4. ✅ Set up CloudWatch log groups

---

## Monitoring

### CloudWatch Logs

**Scheduled Executions**:
```bash
# View daily metrics logs
aws logs tail /aws/lambda/insuremail-ai-dev-evaluation-metrics --follow --since 1h

# Filter for errors
aws logs filter-pattern "ERROR" \
  --log-group-name /aws/lambda/insuremail-ai-dev-evaluation-metrics \
  --start-time $(date -u -d '1 hour ago' +%s)000
```

**API Handler Invocations**:
```bash
# Check api_handlers calling evaluation_metrics
aws logs tail /aws/lambda/insuremail-ai-dev-api-handlers --follow | grep "evaluation_metrics"
```

### EventBridge Metrics

```bash
# Check rule invocation count
aws cloudwatch get-metric-statistics \
  --namespace AWS/Events \
  --metric-name Invocations \
  --dimensions Name=RuleName,Value=insuremail-ai-dev-daily-metrics \
  --start-time $(date -u -d '7 days ago' --iso-8601) \
  --end-time $(date -u --iso-8601) \
  --period 86400 \
  --statistics Sum
```

---

## Testing

### Test Scheduled Execution

Manually trigger the EventBridge rule:

```bash
# Test daily metrics
aws events put-events --entries '[
  {
    "Source": "test",
    "DetailType": "Scheduled Event",
    "Detail": "{\"task_type\":\"all\",\"days\":7}",
    "Resources": ["arn:aws:events:us-east-1:ACCOUNT_ID:rule/insuremail-ai-dev-daily-metrics"]
  }
]'
```

### Test API Integration

```bash
# Call API endpoint
curl -X GET "https://YOUR_API_GATEWAY_URL/api/metrics/models?days=7"

# Should return JSON with model statistics
```

### Test Direct Invocation

```bash
# Invoke Lambda directly
aws lambda invoke \
  --function-name insuremail-ai-dev-evaluation-metrics \
  --payload '{"task_type":"all","days":1}' \
  --log-type Tail \
  output.json

# View response
cat output.json | jq '.statistics'
```

---

## Troubleshooting

### Issue: evaluation_metrics Lambda not found

**Symptom**: api_handlers logs show: `"Error calling evaluation_metrics Lambda"`

**Solution**:
1. Check Lambda exists:
   ```bash
   aws lambda get-function --function-name insuremail-ai-dev-evaluation-metrics
   ```

2. Verify environment variable:
   ```bash
   aws lambda get-function-configuration \
     --function-name insuremail-ai-dev-api-handlers \
     --query 'Environment.Variables.EVALUATION_METRICS_FUNCTION_NAME'
   ```

3. Redeploy if missing:
   ```bash
   cd terraform
   terraform apply -target=module.lambda
   ```

### Issue: Permission denied

**Symptom**: `"User is not authorized to perform: lambda:InvokeFunction"`

**Solution**:
1. Check IAM policy:
   ```bash
   aws iam get-role-policy \
     --role-name insuremail-ai-dev-lambda-execution \
     --policy-name insuremail-ai-dev-lambda-invoke
   ```

2. Redeploy IAM module:
   ```bash
   cd terraform
   terraform apply -target=module.iam
   ```

### Issue: Scheduled execution not working

**Symptom**: No logs in CloudWatch at scheduled times

**Solution**:
1. Check EventBridge rule status:
   ```bash
   aws events describe-rule --name insuremail-ai-dev-daily-metrics
   ```

2. Verify Lambda has EventBridge permission:
   ```bash
   aws lambda get-policy --function-name insuremail-ai-dev-evaluation-metrics
   ```

3. Manually trigger to test:
   ```bash
   aws lambda invoke \
     --function-name insuremail-ai-dev-evaluation-metrics \
     --payload '{"task_type":"all","days":7}' \
     output.json
   ```

### Issue: No metrics data returned

**Symptom**: evaluation_metrics returns empty statistics

**Cause**: No data in MODEL_METRICS_TABLE yet

**Solution**:
1. Run multi-LLM inference to populate metrics:
   ```bash
   python scripts/test_email_workflow.py
   ```

2. Verify metrics exist:
   ```bash
   aws dynamodb scan --table-name insuremail-ai-dev-model-metrics --max-items 5
   ```

3. Wait a few minutes and retry evaluation_metrics

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Evaluation Metrics Lambda                 │
│                                                               │
│  Inputs:                                                      │
│  • task_type (filter by task)                                │
│  • days (time window)                                        │
│                                                               │
│  Processing:                                                  │
│  1. Query MODEL_METRICS_TABLE                                │
│  2. Filter by time window                                    │
│  3. Group by model_name                                      │
│  4. Calculate aggregates (avg, min, max, sum)                │
│                                                               │
│  Outputs:                                                     │
│  • Overall statistics                                        │
│  • Per-model statistics                                      │
│  • Sample count                                              │
└─────────────────────────────────────────────────────────────┘
                          ▲     ▲     ▲
                          │     │     │
            ┌─────────────┘     │     └──────────────┐
            │                   │                     │
┌───────────┴──────┐ ┌──────────┴──────────┐ ┌───────┴────────┐
│  EventBridge     │ │  API Handler        │ │  Manual CLI    │
│  Schedule        │ │  (Dashboard)        │ │  Invocation    │
│                  │ │                     │ │                │
│  Daily: 9am UTC  │ │  GET /api/metrics/  │ │  aws lambda    │
│  Weekly: Sun 0am │ │  models             │ │  invoke        │
└──────────────────┘ └─────────────────────┘ └────────────────┘
```

---

## Summary

✅ **Integrated**: evaluation_metrics is now fully connected to the system
✅ **Automated**: Runs daily and weekly via EventBridge
✅ **API**: Dashboard can query metrics on-demand
✅ **Manual**: Can be invoked via CLI for testing/debugging
✅ **Permissions**: IAM policies properly configured
✅ **Monitored**: CloudWatch logs capture all executions

The evaluation_metrics Lambda is now a **first-class citizen** in the InsureMail AI architecture, providing centralized model performance analytics across all integration points.
