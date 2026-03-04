# RAG (Retrieval-Augmented Generation) Setup Guide

Complete guide for setting up and using the RAG knowledge base system.

## Overview

The RAG system enhances AI responses by retrieving relevant context from your insurance knowledge base before generating responses.

**Flow:**
```
Document Upload → S3 (knowledge_base bucket)
       ↓
   RAG Ingestion Lambda (automatic trigger)
       ↓
   Generate Embeddings (Titan Embeddings)
       ↓
   Store in DynamoDB (embeddings table)
       ↓
Email Processing → RAG Retrieval → Top 3 Relevant Docs → Claude Response
```

---

## Quick Start

### 1. Upload Knowledge Base Documents

```bash
./scripts/upload_knowledge_base.sh
```

This interactive script allows you to:
- Upload test/sample documents
- Upload custom documents
- List current documents
- Delete documents

### 2. Verify Processing

```bash
# Check ingestion logs
aws logs tail /aws/lambda/insuremail-ai-dev-rag-ingestion --follow

# Count embeddings
cd terraform
aws dynamodb scan \
  --table-name $(terraform output -raw embeddings_table_name) \
  --select COUNT
```

### 3. Test Retrieval

Send a test email and verify that relevant documents are retrieved in the processing logs.

---

## Architecture

### Components

#### 1. S3 Knowledge Base Bucket
- **Location**: `insuremail-ai-dev-knowledge-base`
- **Prefix**: `documents/` (all docs must be in this prefix)
- **Trigger**: Automatic Lambda invocation on upload

#### 2. RAG Ingestion Lambda
- **Trigger**: S3 ObjectCreated event
- **Function**: Process documents and generate embeddings
- **Output**: Stores embeddings in DynamoDB

**Process:**
1. Reads document from S3
2. Chunks text (500 tokens, 50 token overlap)
3. Generates embeddings via Titan
4. Stores in DynamoDB with metadata

#### 3. DynamoDB Embeddings Table
- **Primary Key**: `doc_id` (UUID)
- **Attributes**:
  - `doc_id`: Unique document ID
  - `s3_key`: Original S3 location
  - `chunk_text`: Text content
  - `embedding`: Vector embedding (1536 dimensions)
  - `metadata`: Document metadata
  - `timestamp`: Upload time

#### 4. RAG Retrieval Lambda
- **Trigger**: Step Functions (during email processing)
- **Function**: Semantic search for relevant documents
- **Output**: Top 3 most relevant documents

**Process:**
1. Generate embedding for email text
2. Scan DynamoDB and calculate cosine similarity
3. Return top-K most similar documents

---

## Supported Document Formats

### Currently Supported
- ✅ **Plain text** (.txt)
- ✅ **JSON** (.json)
- ✅ **Markdown** (.md)

### Planned Support
- ⏳ **PDF** (.pdf) - Requires PyPDF2
- ⏳ **Word** (.docx) - Requires python-docx
- ⏳ **HTML** (.html) - Requires BeautifulSoup

---

## Document Preparation

### Best Practices

#### 1. Structure Your Documents
```
documents/
├── policies/
│   ├── health_insurance_policy.txt
│   ├── auto_insurance_policy.txt
│   └── life_insurance_policy.txt
├── procedures/
│   ├── claim_filing_process.txt
│   ├── appeal_process.txt
│   └── refund_process.txt
├── faq/
│   ├── common_questions.txt
│   └── coverage_questions.txt
└── compliance/
    ├── hipaa_guidelines.txt
    └── gdpr_guidelines.txt
```

#### 2. Document Format
```
# Title: Health Insurance Claims Process

## Overview
When filing a health insurance claim, follow these steps...

## Required Documents
1. Completed claim form
2. Itemized bill from provider
3. Proof of payment
...

## Important Notes
- Claims must be filed within 90 days
- Pre-authorization required for procedures over $5,000
```

#### 3. Chunking Guidelines
- **Keep sections focused**: Each section should cover one topic
- **Optimal chunk size**: 200-500 words
- **Clear headings**: Use markdown headers
- **Include context**: Each chunk should be self-contained

---

## Manual Upload

### Upload Single File
```bash
cd terraform
KB_BUCKET=$(terraform output -raw knowledge_base_bucket_name)

# Upload file
aws s3 cp /path/to/document.txt s3://$KB_BUCKET/documents/policies/document.txt
```

### Upload Directory
```bash
# Upload entire directory
aws s3 sync /path/to/docs/ s3://$KB_BUCKET/documents/
```

### Upload with Metadata
```bash
# Add metadata tags
aws s3 cp document.txt s3://$KB_BUCKET/documents/document.txt \
  --metadata category=policy,version=2024,department=claims
```

---

## Testing RAG

### Test Ingestion

```bash
# 1. Upload a test document
echo "Test insurance policy: Claims must be filed within 90 days." > test_policy.txt
aws s3 cp test_policy.txt s3://$KB_BUCKET/documents/test_policy.txt

# 2. Wait 10 seconds for processing

# 3. Check if embedding was created
aws dynamodb scan \
  --table-name $(terraform output -raw embeddings_table_name) \
  --filter-expression "contains(s3_key, :key)" \
  --expression-attribute-values '{":key":{"S":"test_policy.txt"}}'
```

### Test Retrieval

```bash
# Invoke retrieval Lambda directly
aws lambda invoke \
  --function-name insuremail-ai-dev-rag-retrieval \
  --payload '{
    "email_text": "How long do I have to file a claim?",
    "top_k": 3
  }' \
  output.json

# View results
cat output.json | jq '.retrieved_documents'
```

### Test End-to-End

```bash
# Send test email that should trigger RAG
echo "I want to know about the claim filing deadline" | \
  mail -s "Claim Question" support@yourdomain.com

# Check Step Functions execution
aws stepfunctions list-executions \
  --state-machine-arn $(terraform output -raw state_machine_arn) \
  --max-results 1

# View execution details
aws stepfunctions describe-execution \
  --execution-arn <execution-arn-from-above>
```

---

## Monitoring

### CloudWatch Metrics

```bash
# Ingestion Lambda invocations
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=insuremail-ai-dev-rag-ingestion \
  --statistics Sum \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600

# Retrieval Lambda latency
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=insuremail-ai-dev-rag-retrieval \
  --statistics Average,Maximum \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600
```

### Logs

```bash
# Ingestion logs
aws logs tail /aws/lambda/insuremail-ai-dev-rag-ingestion --follow

# Retrieval logs
aws logs tail /aws/lambda/insuremail-ai-dev-rag-retrieval --follow

# Filter for errors
aws logs filter-log-events \
  --log-group-name /aws/lambda/insuremail-ai-dev-rag-ingestion \
  --filter-pattern "ERROR"
```

---

## Troubleshooting

### Issue: Documents uploaded but not processed

**Symptoms:**
- Files in S3 but no embeddings in DynamoDB
- No logs in CloudWatch

**Debug steps:**
```bash
# 1. Check if S3 notification is configured
aws s3api get-bucket-notification-configuration \
  --bucket $KB_BUCKET

# 2. Check Lambda permissions
aws lambda get-policy \
  --function-name insuremail-ai-dev-rag-ingestion

# 3. Manually invoke Lambda
aws lambda invoke \
  --function-name insuremail-ai-dev-rag-ingestion \
  --payload '{
    "Records": [{
      "s3": {
        "bucket": {"name": "'$KB_BUCKET'"},
        "object": {"key": "documents/test.txt"}
      }
    }]
  }' \
  response.json
```

**Solution:**
```bash
# Re-apply Terraform to fix notifications
cd terraform
terraform apply -target=module.storage.aws_s3_bucket_notification.knowledge_base
```

### Issue: Retrieval not finding relevant documents

**Symptoms:**
- Retrieved documents seem random
- Low similarity scores

**Possible causes:**
1. **Document quality**: Text too short or not descriptive
2. **Chunking**: Chunks too large/small
3. **Embedding quality**: Using wrong model

**Solutions:**
```bash
# 1. Check embedding dimensionality
aws dynamodb get-item \
  --table-name $(terraform output -raw embeddings_table_name) \
  --key '{"doc_id":{"S":"<some-doc-id>"}}' \
  | jq '.Item.embedding.L | length'
# Should be 1536 for Titan Embeddings

# 2. Test similarity calculation manually
# Review lambda/rag_retrieval/lambda_function.py

# 3. Re-process documents with better chunking
# Delete and re-upload documents
```

### Issue: High costs from embeddings

**Symptoms:**
- Bedrock costs higher than expected

**Optimization:**
```bash
# 1. Check number of embeddings
aws dynamodb scan \
  --table-name $(terraform output -raw embeddings_table_name) \
  --select COUNT

# 2. Remove duplicate or unnecessary documents
./scripts/upload_knowledge_base.sh
# Select option 4 to delete old documents

# 3. Optimize chunk size (increase chunk_size to reduce embeddings)
# Edit lambda/rag_ingestion/lambda_function.py:
# CHUNK_SIZE = 1000  # Instead of 500
```

---

## Cost Optimization

### Current Costs

**For 100 knowledge base documents:**
- Storage (S3): ~$0.02/month
- Embeddings (DynamoDB): ~$0.10/month
- Ingestion (one-time):
  - Lambda: ~$0.01
  - Titan Embeddings: ~$0.50
- Retrieval (per email): ~$0.0001

**Monthly cost for 1,000 emails/day:** ~$3 for RAG

### Optimization Strategies

1. **Larger chunks** = Fewer embeddings = Lower cost
2. **Deduplicate content** before uploading
3. **Cache** frequently retrieved documents
4. **Limit** retrieval to top-3 (already implemented)

---

## Advanced Features

### Custom Embeddings Model

To use a different embedding model:

```python
# In lambda/rag_ingestion/lambda_function.py
EMBEDDING_MODEL = "amazon.titan-embed-text-v2"  # Newer model
# Or
EMBEDDING_MODEL = "cohere.embed-english-v3"  # Alternative provider
```

### Metadata Filtering

Filter by metadata during retrieval:

```python
# In lambda/rag_retrieval/lambda_function.py
def retrieve_documents(email_text, category=None):
    # Add filter expression for DynamoDB scan
    if category:
        filter_expression = "metadata.category = :cat"
```

### Multi-Language Support

Process documents in multiple languages:

```python
# Detect language and use appropriate chunking
from langdetect import detect

language = detect(document_text)
if language == 'es':
    # Spanish-specific processing
elif language == 'fr':
    # French-specific processing
```

---

## Summary

**RAG Setup Checklist:**
- [x] S3 bucket created (knowledge_base)
- [x] RAG ingestion Lambda deployed
- [x] S3 trigger configured (ObjectCreated)
- [x] DynamoDB embeddings table created
- [x] RAG retrieval Lambda integrated in workflow
- [ ] Knowledge base documents uploaded
- [ ] Ingestion tested and verified
- [ ] Retrieval tested with sample emails

**Next Steps:**
1. Run `./scripts/upload_knowledge_base.sh` to upload documents
2. Test with `./scripts/test_pipeline.sh`
3. Monitor logs and verify embeddings are created
4. Send test emails and check RAG retrieval in Step Functions logs

For questions or issues:
- Check CloudWatch Logs
- Review [EMAIL_INTEGRATION.md](EMAIL_INTEGRATION.md) for end-to-end testing
- See [COST_OPTIMIZATION.md](COST_OPTIMIZATION.md) for reducing RAG costs
