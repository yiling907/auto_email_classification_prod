# InsureMail AI - System Architecture

Technical overview of the InsureMail AI system architecture, data flows, and design decisions.

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Data Flow](#data-flow)
3. [Component Details](#component-details)
4. [Design Decisions](#design-decisions)
5. [Scalability](#scalability)

---

## High-Level Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Email Sources                           │
│  (SES Receiving, Manual Upload, Simulation Script)              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    S3 Bucket (Emails)                           │
│              insuremail-ai-dev-emails                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│               SNS Topic (ses-notifications)                     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│          Lambda: Email Receiver (Trigger)                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│         Step Functions State Machine (Orchestration)            │
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │
│  │ Email Parser │────▶│ Multi-LLM    │────▶│ RAG Retrieval│   │
│  │              │     │ Inference    │     │              │   │
│  │              │     │ (Parallel)   │     │              │   │
│  └──────────────┘     └──────────────┘     └──────────────┘   │
│                                                    │             │
│                                                    ▼             │
│                            ┌──────────────────────────────┐     │
│                            │ CRM Validation + Fraud Check │     │
│                            └──────────────┬───────────────┘     │
│                                           │                      │
│                                           ▼                      │
│                            ┌──────────────────────────────┐     │
│                            │  Claude Response Generation  │     │
│                            └──────────────┬───────────────┘     │
│                                           │                      │
│                      ┌────────────────────┴────────────────┐    │
│                      ▼                                      ▼    │
│            ┌─────────────────┐                  ┌──────────────┐│
│            │ Auto-Send       │                  │ Human Review ││
│            │ (Confidence≥0.8)│                  │ (Conf<0.8)   ││
│            └─────────────────┘                  └──────────────┘│
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data Storage Layer                           │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐ │
│  │ DynamoDB:        │  │ DynamoDB:        │  │ DynamoDB:    │ │
│  │ Emails           │  │ Model Metrics    │  │ Embeddings   │ │
│  └──────────────────┘  └──────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 Monitoring & Analytics                          │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐ │
│  │ CloudWatch Logs  │  │ Evaluation       │  │ Dashboard    │ │
│  │                  │  │ Metrics Lambda   │  │ (React+S3)   │ │
│  └──────────────────┘  └──────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Email Processing Flow

#### 1. Email Ingestion

```
External Email
  → SES (if custom domain configured)
  → S3 Bucket (incoming/)
  → SNS Topic Notification
  → Email Receiver Lambda
  → Step Functions Execution Starts
```

**Alternative (Testing)**:
```
Manual Upload (simulate_email_workflow.sh)
  → S3 Bucket (incoming/)
  → Step Functions (manual trigger)
```

#### 2. Parsing & Analysis

```
Step Functions State Machine:

Step 1: Email Parser Lambda
  Input: S3 object key
  Output: {
    email_id: UUID,
    from: string,
    to: string,
    subject: string,
    body: string (PII redacted),
    timestamp: ISO date
  }
  Storage: DynamoDB (emails table)

Step 2: Parallel Processing
  Branch A: Intent Classification (Multi-LLM Lambda)
    - Invokes Mistral 7B + Llama 3.1 8B
    - Compares outputs
    - Stores metrics
    Output: {intent: "claim_inquiry", confidence: 0.85}

  Branch B: Entity Extraction (Multi-LLM Lambda)
    - Extracts policy_number, member_name, dates, amounts
    Output: {entities: {...}}

Step 3: RAG Retrieval Lambda
  Input: Email body + intent
  Process:
    1. Generate embedding (Titan Embeddings)
    2. Cosine similarity search in DynamoDB
    3. Return top-3 relevant documents
  Output: {
    retrieved_docs: [
      {doc_id, chunk_text, similarity_score},
      ...
    ]
  }
```

#### 3. Validation & Response

```
Step 4: CRM Validation (Mock)
  Check if policy_number exists in DynamoDB
  Output: {valid: true/false}

Step 5: Fraud Risk Assessment (Rule-based)
  Rules:
    - Claim amount > $10,000 → High Risk
    - Unknown policy → High Risk
    - Otherwise → Low Risk
  Output: {fraud_risk: "low"}

Step 6: Claude Response Generation Lambda
  Input: {
    email_body,
    intent,
    entities,
    rag_context,
    crm_status,
    fraud_risk
  }

  Process:
    1. Build structured prompt with all context
    2. Invoke Mistral 7B (primary) or Llama 3.1 8B (fallback)
    3. Parse JSON response
    4. Extract confidence score

  Output: {
    response_text: string,
    confidence_score: float (0-1),
    references: [doc_ids],
    compliance_check: "passed"
  }

  Storage: DynamoDB (emails table - update with response)
```

#### 4. Routing Decision

```
If confidence ≥ 0.8:
  → Auto-send email via SES
  → Mark as "auto_responded"

Else if confidence ≥ 0.5:
  → Store in "pending_review" queue
  → Notify human reviewer (future: SNS/SQS)

Else:
  → Escalate to agent
  → Mark as "escalated"
```

### Metrics Collection Flow

```
Multi-LLM Inference Lambda (during execution)
  → Collects: {
       task_type,
       model_name,
       input_tokens,
       output_tokens,
       latency_ms,
       cost_usd,
       timestamp
     }
  → Stores in DynamoDB (model_metrics table)

EventBridge Rule (Daily 9am UTC)
  → Triggers: Evaluation Metrics Lambda
  → Aggregates: Last 7 days of metrics
  → Calculates: Average latency, total cost, accuracy
  → Returns: Statistics by model and task

API Handlers Lambda (On dashboard query)
  → Invokes: Evaluation Metrics Lambda
  → Returns: Real-time statistics
```

---

## Component Details

### Lambda Functions

#### 1. Email Receiver (`email-receiver`)
- **Trigger**: SNS topic (SES notification)
- **Purpose**: Parse SNS message, extract S3 key, trigger Step Functions
- **Timeout**: 30s
- **Memory**: 128 MB

#### 2. Email Parser (`email-parser`)
- **Trigger**: Step Functions
- **Purpose**: Parse raw email from S3, extract fields, redact PII
- **Timeout**: 60s
- **Memory**: 256 MB

#### 3. Multi-LLM Inference (`multi-llm-inference`)
- **Trigger**: Step Functions
- **Purpose**: Run parallel model inference, collect metrics
- **Models**: Mistral 7B, Llama 3.1 8B
- **Timeout**: 120s
- **Memory**: 512 MB

#### 4. RAG Ingestion (`rag-ingestion`)
- **Trigger**: S3 event (knowledge base uploads)
- **Purpose**: Chunk documents, generate embeddings, store in DynamoDB
- **Timeout**: 300s
- **Memory**: 512 MB

#### 5. RAG Retrieval (`rag-retrieval`)
- **Trigger**: Step Functions
- **Purpose**: Semantic search for relevant documents
- **Timeout**: 60s
- **Memory**: 256 MB

#### 6. Claude Response (`claude-response`)
- **Trigger**: Step Functions
- **Purpose**: Generate high-confidence response with RAG context
- **Timeout**: 120s
- **Memory**: 512 MB

#### 7. Evaluation Metrics (`evaluation-metrics`)
- **Trigger**: EventBridge schedule, API handlers
- **Purpose**: Aggregate and analyze model performance
- **Timeout**: 60s
- **Memory**: 256 MB

#### 8. Email Sender (`email-sender`)
- **Trigger**: Step Functions (auto-send path)
- **Purpose**: Send email via SES
- **Timeout**: 30s
- **Memory**: 128 MB

#### 9. API Handlers (`api-handlers`)
- **Trigger**: API Gateway
- **Purpose**: Serve dashboard API requests
- **Timeout**: 30s
- **Memory**: 256 MB

### DynamoDB Tables

#### emails
```
PK: email_id (UUID)
Attributes:
  - from, to, subject, body
  - intent, entities
  - response_text, confidence_score
  - status (pending/auto_responded/escalated)
  - rag_references
  - timestamp
```

#### model_metrics
```
PK: email_id
SK: model_name + task_type
Attributes:
  - input_tokens, output_tokens
  - latency_ms, cost_usd
  - timestamp
```

#### embeddings
```
PK: doc_id (UUID)
Attributes:
  - doc_name
  - chunk_index
  - chunk_text
  - embedding (JSON string of float array)
  - metadata (category, source)
```

### Step Functions State Machine

**States:**
1. **Parse Email** (Task) → email-parser Lambda
2. **Parallel Processing** (Parallel)
   - Branch: Intent Classification
   - Branch: Entity Extraction
3. **RAG Retrieval** (Task) → rag-retrieval Lambda
4. **CRM Validation** (Task) → Mock validation logic
5. **Fraud Assessment** (Task) → Rule-based scoring
6. **Generate Response** (Task) → claude-response Lambda
7. **Route Response** (Choice)
   - Path A: Auto-send (confidence ≥ 0.8)
   - Path B: Human review (confidence ≥ 0.5)
   - Path C: Escalate (confidence < 0.5)

**Error Handling:**
- Retry with exponential backoff (3 attempts)
- Catch all errors → store in DynamoDB with "error" status
- Log to CloudWatch

---

## Design Decisions

### Why Serverless?

**Pros:**
- ✅ No server management
- ✅ Auto-scaling
- ✅ Pay-per-use pricing
- ✅ High availability (AWS-managed)

**Cons:**
- ❌ Cold start latency (mitigated with provisioned concurrency if needed)
- ❌ Execution time limits (max 15 minutes)

### Why Step Functions?

**Alternatives Considered:**
- Direct Lambda chaining (harder to debug)
- SQS queues (less visibility)
- ECS tasks (more expensive)

**Chosen for:**
- ✅ Visual workflow representation
- ✅ Built-in error handling and retries
- ✅ State persistence
- ✅ Easy debugging with execution history

### Why DynamoDB?

**Alternatives Considered:**
- RDS/Aurora (more expensive, overkill for our access patterns)
- MongoDB Atlas (external dependency)
- S3 (no querying capability)

**Chosen for:**
- ✅ Serverless (no provisioning)
- ✅ Pay-per-request pricing
- ✅ Single-digit millisecond latency
- ✅ Built-in encryption

**Limitation:** Vector search not optimized (using scan with cosine similarity)

**Future:** Migrate to OpenSearch/Pinecone for production-scale RAG

### Why Mistral 7B Primary?

**Cost Comparison** (per 1M tokens):
- Claude 3 Sonnet: $3.00 input / $15.00 output
- Mistral 7B: $0.15 input / $0.20 output
- Llama 3.1 8B: $0.30 input / $0.60 output

**Decision:** Mistral 7B offers best cost/performance ratio for insurance domain

**Accuracy:** Sufficient for classification and entity extraction (90%+ in testing)

---

## Scalability

### Current Limits

- **Lambda concurrency**: 1,000 (regional default)
- **DynamoDB**: Unlimited (pay-per-request)
- **S3**: Unlimited
- **Step Functions**: 1M executions/month free tier

### Scaling Strategy

#### Horizontal Scaling
- Lambda auto-scales to 1,000 concurrent executions
- No code changes needed
- Add provisioned concurrency if cold starts become issue

#### Vertical Scaling
- Increase Lambda memory (scales CPU proportionally)
- Current: 256-512 MB
- Max: 10,240 MB

### Performance Targets

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Email processing time | <30s | ~20-25s | ✅ |
| RAG retrieval | <2s | ~1s | ✅ |
| Model inference | <10s | ~5-8s | ✅ |
| Dashboard load time | <3s | ~2s | ✅ |
| Cost per email | <$0.02 | ~$0.015 | ✅ |

### Cost at Scale

**100 emails/day** (~3,000/month):
- Bedrock: $5
- Lambda: <$1 (free tier)
- DynamoDB: <$1 (free tier)
- **Total: ~$6/month**

**1,000 emails/day** (~30,000/month):
- Bedrock: $50
- Lambda: $5
- DynamoDB: $10
- **Total: ~$65/month**

**10,000 emails/day** (~300,000/month):
- Bedrock: $500
- Lambda: $50
- DynamoDB: $100
- **Total: ~$650/month**

See [COST_OPTIMIZATION.md](./COST_OPTIMIZATION.md) for detailed breakdown.

---

## Security Architecture

### IAM Roles

**Lambda Execution Role:**
```
Permissions:
  - logs:CreateLogGroup, PutLogEvents
  - s3:GetObject (emails bucket)
  - s3:PutObject (logs bucket)
  - dynamodb:GetItem, PutItem, Scan, Query
  - bedrock:InvokeModel
  - ses:SendEmail
  - lambda:InvokeFunction
```

**Step Functions Role:**
```
Permissions:
  - lambda:InvokeFunction (all project Lambdas)
  - logs:CreateLogGroup, PutLogEvents
```

### Data Encryption

- **At Rest**: All S3 buckets and DynamoDB tables use AWS-managed encryption (AES-256)
- **In Transit**: TLS 1.2+ for all AWS service communication
- **PII Redaction**: Email parser redacts SSN, credit card numbers, phone numbers before storage

### Network Security

**Current:** Public Lambda functions (no VPC)

**Production TODO:**
- Place Lambdas in private VPC subnets
- Use VPC endpoints for AWS service access
- NAT Gateway for internet access (if needed)

---

## Monitoring Architecture

### CloudWatch Integration

**Logs:**
- All Lambda functions log to `/aws/lambda/insuremail-ai-dev-*`
- Step Functions logs execution history
- Structured logging with trace IDs

**Metrics:**
- Lambda invocations, errors, duration
- DynamoDB consumed capacity
- Step Functions execution success/failure
- Custom metrics for model performance

**Alarms:**
- Lambda error rate > 1%
- Step Functions execution failures
- DynamoDB throttling
- Bedrock API errors

### X-Ray Tracing

**Status:** Enabled but not yet configured

**Future:** Add X-Ray to trace full request flow across services

---

## Future Architecture Enhancements

### Phase 2: Production Hardening
1. VPC configuration
2. Secrets Manager for API keys
3. CI/CD pipeline (GitHub Actions → Terraform Cloud)
4. Multi-region deployment

### Phase 3: Advanced Features
1. Real-time streaming (Kinesis)
2. Caching layer (ElastiCache)
3. Vector database (OpenSearch/Pinecone)
4. A/B testing framework

### Phase 4: Enterprise Features
1. Multi-tenancy
2. SLA guarantees
3. Advanced analytics (Athena, QuickSight)
4. Compliance reporting (SOC 2, HIPAA)

---

**See Also:**
- [MODEL_METRICS_DATA_FLOW.md](./MODEL_METRICS_DATA_FLOW.md) - Metrics collection details
- [Deployment Guide](../guides/DEPLOYMENT.md) - Setup instructions
- [ROADMAP.md](../ROADMAP.md) - Future enhancements

**Last Updated:** March 4, 2026
