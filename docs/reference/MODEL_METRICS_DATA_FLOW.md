# Model Metrics Data Flow

## Where Data Gets Saved to `insuremail-ai-dev-model-metrics`

---

## **Answer: Multi-LLM Inference Lambda**

The `insuremail-ai-dev-model-metrics` DynamoDB table is populated by the **`classify_intent` Lambda function**.

---

## **Data Flow Diagram**

```
Email Received (SES)
  ↓
Email Receiver Lambda
  ↓
Step Functions Execution
  ↓
Parse Email Lambda
  ↓
┌─────────────────────────────────────────────────────┐
│  Parallel Analysis (Step Functions Parallel State)  │
│                                                      │
│  Branch 1: Intent Classification                    │
│  ┌────────────────────────────────────────┐        │
│  │  Multi-LLM Inference Lambda            │        │
│  │  (intent_classification)               │        │
│  │                                         │        │
│  │  1. Runs Mistral 7B                    │        │
│  │  2. Runs Llama 3.1 8B                  │        │
│  │  3. Collects metrics for each          │        │
│  │     - Input tokens                     │        │
│  │     - Output tokens                    │        │
│  │     - Latency (ms)                     │        │
│  │     - Cost (USD)                       │        │
│  │     - Success/failure                  │        │
│  │                                         │        │
│  │  4. Calls store_metrics() for each     │        │
│  │     model                               │        │
│  │        ↓                                │        │
│  │     DynamoDB.put_item()                │        │
│  │        ↓                                │        │
│  │  💾 insuremail-ai-dev-model-metrics    │ ◄──── DATA SAVED HERE!
│  └────────────────────────────────────────┘        │
│                                                      │
│  Branch 2: Entity Extraction                        │
│  ┌────────────────────────────────────────┐        │
│  │  Multi-LLM Inference Lambda            │        │
│  │  (entity_extraction)                   │        │
│  │                                         │        │
│  │  1. Runs Mistral 7B                    │        │
│  │  2. Runs Llama 3.1 8B                  │        │
│  │  3. Stores metrics                     │        │
│  │        ↓                                │        │
│  │  💾 insuremail-ai-dev-model-metrics    │ ◄──── DATA SAVED HERE!
│  └────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────┘
  ↓
RAG Retrieval
  ↓
Response Generation (Mistral/Llama)
  ↓
Send Email
```

---

## **Code Location**

### **File**: `lambda/classify_intent/lambda_function.py`

### **Function**: `store_metrics()` (lines 259-281)

```python
def store_metrics(task_type: str, model_name: str, result: Dict[str, Any]) -> None:
    """Store model performance metrics in DynamoDB"""
    try:
        timestamp = datetime.utcnow().isoformat() + 'Z'
        model_timestamp = f"{model_name}#{timestamp}"

        item = {
            'task_type': task_type,              # "intent_classification" or "entity_extraction"
            'model_timestamp': model_timestamp,   # Sort key: "mistral-7b#2026-03-04T12:34:56.789Z"
            'model_name': model_name,            # "mistral-7b" or "llama-3.1-8b"
            'model_id': result.get('model_id'), # Full Bedrock model ID
            'input_tokens': result.get('input_tokens', 0),
            'output_tokens': result.get('output_tokens', 0),
            'latency_ms': result.get('latency_ms', 0),
            'cost_usd': result.get('cost_usd', 0),
            'success': result.get('success', False),
            'timestamp': timestamp
        }

        model_metrics_table.put_item(Item=item)  # ← DATA SAVED HERE!

    except Exception as e:
        print(f"Error storing metrics: {str(e)}")
```

### **Called From**: `invoke_model()` (line 237)

```python
def invoke_model(model_name, model_config, prompt, task_type):
    # ... invoke Bedrock model ...

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

    # Store metrics ← CALL HAPPENS HERE
    store_metrics(task_type, model_name, result)

    return result
```

---

## **When Does Data Get Saved?**

### **Trigger**: Every time an email is processed

1. **Email arrives** → SES receives it
2. **Email receiver Lambda** → Triggers Step Functions
3. **Step Functions** → Runs parallel analysis:
   - **Intent Classification** → Calls `classify_intent` with `task_type="intent_classification"`
   - **Entity Extraction** → Calls `classify_intent` with `task_type="entity_extraction"`
4. **Multi-LLM Inference runs**:
   - Invokes **Mistral 7B** → Stores metrics
   - Invokes **Llama 3.1 8B** → Stores metrics
5. **Result**: 4 records saved per email (2 models × 2 tasks)

---

## **DynamoDB Table Schema**

### **Table Name**: `insuremail-ai-dev-model-metrics`

### **Keys**:
- **Partition Key**: `task_type` (String) - e.g., `"intent_classification"`, `"entity_extraction"`
- **Sort Key**: `model_timestamp` (String) - e.g., `"mistral-7b#2026-03-04T12:34:56.789Z"`

### **Attributes**:
```json
{
  "task_type": "intent_classification",
  "model_timestamp": "mistral-7b#2026-03-04T12:34:56.789Z",
  "model_name": "mistral-7b",
  "model_id": "mistral.mistral-7b-instruct-v0:2",
  "input_tokens": 450,
  "output_tokens": 85,
  "latency_ms": 1850,
  "cost_usd": 0.000085,
  "success": true,
  "timestamp": "2026-03-04T12:34:56.789Z"
}
```

---

## **Why Is The Table Empty?**

The table is currently empty because:

1. ✅ **Infrastructure deployed** - Table exists
2. ✅ **Lambda function deployed** - classify_intent exists
3. ❌ **No emails processed yet** - Need to trigger the workflow

### **To Populate Data**:

You need to **send a test email** through the system:

```bash
# Option 1: Send real email to your verified SES address
# (From your email client to shiyizhiya@gmail.com)

# Option 2: Use test script
python scripts/test_email_workflow.py

# Option 3: Manually trigger Step Functions
aws stepfunctions start-execution \
  --state-machine-arn "arn:aws:states:us-east-1:970850578809:stateMachine:insuremail-ai-dev-email-processing" \
  --input file://tests/test_data/sample_step_functions_input.json
```

---

## **Step Functions Configuration**

### **File**: `step-functions/email_processing_workflow.json`

### **Intent Classification Step** (lines 23-38):
```json
{
  "Type": "Task",
  "Resource": "${classify_intent_lambda_arn}",
  "Comment": "Classify email intent using multiple LLMs",
  "Parameters": {
    "prompt.$": "States.Format('Classify the intent of this email into one of: claim_inquiry, policy_question, complaint, general_inquiry. Email: {}', $.parsed_email.parsed_data.body)",
    "task_type": "intent_classification"  ← PASSED TO LAMBDA
  },
  "ResultPath": "$.intent",
  "End": true
}
```

### **Entity Extraction Step** (lines 40-56):
```json
{
  "Type": "Task",
  "Resource": "${classify_intent_lambda_arn}",
  "Comment": "Extract entities using multiple LLMs",
  "Parameters": {
    "prompt.$": "States.Format('Extract entities (policy number, member name, claim amount, dates) from: {}', $.parsed_email.parsed_data.body)",
    "task_type": "entity_extraction"  ← PASSED TO LAMBDA
  },
  "ResultPath": "$.entities",
  "End": true
}
```

---

## **How To Verify Data Is Being Saved**

### **1. Check DynamoDB Table**
```bash
# Count total items
aws dynamodb scan --table-name insuremail-ai-dev-model-metrics --select COUNT

# View recent items
aws dynamodb scan --table-name insuremail-ai-dev-model-metrics --max-items 5
```

### **2. Check Lambda Logs**
```bash
# View classify_intent logs
aws logs tail /aws/lambda/insuremail-ai-dev-multi-llm-inference --follow

# Filter for metrics storage
aws logs filter-pattern "Stored embedding" \
  --log-group-name /aws/lambda/insuremail-ai-dev-multi-llm-inference
```

### **3. Check Step Functions Execution**
```bash
# List recent executions
aws stepfunctions list-executions \
  --state-machine-arn "arn:aws:states:us-east-1:970850578809:stateMachine:insuremail-ai-dev-email-processing" \
  --max-results 5

# View execution details
aws stepfunctions describe-execution \
  --execution-arn "YOUR_EXECUTION_ARN"
```

---

## **Complete Data Flow Example**

### **Input**: Email arrives at `shiyizhiya@gmail.com`

```
Subject: Question about my claim
Body: I submitted a claim last week (Policy #12345) for $500.
      What is the status?
```

### **Processing**:

1. **Email Receiver** → Triggers Step Functions
2. **Email Parser** → Extracts subject/body
3. **Parallel Analysis**:

   **Intent Classification Branch**:
   ```python
   # classify_intent called with:
   task_type = "intent_classification"
   prompt = "Classify the intent of this email into one of: claim_inquiry, ..."

   # Runs Mistral 7B:
   → Output: "claim_inquiry"
   → Metrics: {input_tokens: 450, output_tokens: 10, latency_ms: 1850, cost: $0.0000825}
   → store_metrics() called
   → DynamoDB record #1 saved ✅

   # Runs Llama 3.1 8B:
   → Output: "claim_inquiry"
   → Metrics: {input_tokens: 450, output_tokens: 12, latency_ms: 2100, cost: $0.000207}
   → store_metrics() called
   → DynamoDB record #2 saved ✅
   ```

   **Entity Extraction Branch**:
   ```python
   # classify_intent called with:
   task_type = "entity_extraction"
   prompt = "Extract entities (policy number, member name, ...) from: ..."

   # Runs Mistral 7B:
   → Output: {"policy_number": "12345", "claim_amount": "$500"}
   → Metrics: {input_tokens: 480, output_tokens: 45, latency_ms: 1920, cost: $0.000081}
   → store_metrics() called
   → DynamoDB record #3 saved ✅

   # Runs Llama 3.1 8B:
   → Output: {"policy_number": "12345", "claim_amount": "$500"}
   → Metrics: {input_tokens: 480, output_tokens: 50, latency_ms: 2250, cost: $0.000174}
   → store_metrics() called
   → DynamoDB record #4 saved ✅
   ```

### **Result**: 4 records in `insuremail-ai-dev-model-metrics` table

```bash
$ aws dynamodb scan --table-name insuremail-ai-dev-model-metrics --select COUNT

{
  "Count": 4,
  "ScannedCount": 4
}
```

---

## **Summary**

| Question | Answer |
|----------|--------|
| **Where?** | `lambda/classify_intent/lambda_function.py` line 278 |
| **When?** | Every time an email is processed (2 models × 2 tasks = 4 records per email) |
| **What?** | Model performance metrics (tokens, latency, cost, success) |
| **Why empty?** | No emails processed yet - need to send test email |
| **How to populate?** | Send email to `shiyizhiya@gmail.com` or run test script |

---

## **Next Steps**

To see data in the table:

1. **Send a test email** to your verified SES address (`shiyizhiya@gmail.com`)
2. **Wait 10-20 seconds** for processing
3. **Check DynamoDB**:
   ```bash
   aws dynamodb scan --table-name insuremail-ai-dev-model-metrics --max-items 5
   ```
4. **View evaluation metrics**:
   ```bash
   aws lambda invoke \
     --function-name insuremail-ai-dev-evaluation-metrics \
     --cli-binary-format raw-in-base64-out \
     --payload file://<(echo '{"task_type":"all","days":7}') \
     output.json

   cat output.json | jq '.statistics'
   ```

The metrics will then be available for:
- ✅ Dashboard API queries
- ✅ Automated daily/weekly reports
- ✅ Model performance comparison
