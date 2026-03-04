# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**InsureMail AI** - An AI-powered automated email response system for insurance companies using AWS Bedrock (Claude 3), Terraform, and serverless architecture.

The complete project specification is in `claude.md`. This file provides practical development guidance.

## Architecture

### Technology Stack
- **Cloud Platform**: AWS (Bedrock, Lambda, Step Functions, S3, DynamoDB, CloudWatch, API Gateway)
- **Infrastructure as Code**: Terraform
- **Primary AI Model**: Claude 3 (Sonnet for production, Haiku for evaluation)
- **Additional Models**: Amazon Titan, Llama 3, Mistral (for benchmarking)
- **Language**: Python 3.11+ (Lambda runtime)
- **Frontend**: React (S3 + CloudFront static hosting)

### System Components
1. **Infrastructure Layer**: Terraform modules for all AWS resources
2. **Data Layer**: Email parsing, entity extraction, RAG pipeline
3. **AI Orchestration**: Step Functions state machine coordinating Lambda functions
4. **Evaluation Layer**: Multi-LLM benchmarking and metrics
5. **Observability**: CloudWatch logging/metrics + React dashboard

## Key Technical Requirements

### Terraform Conventions
- Use modular structure (separate modules for IAM, storage, compute, monitoring)
- All resources must be tagged: `Project=InsureMailAI`, `ManagedBy=Terraform`
- Use `PAY_PER_REQUEST` billing for DynamoDB (cost optimization)
- Enable versioning and encryption for all S3 buckets
- Implement least-privilege IAM policies

### Lambda Best Practices
- Python 3.11 or higher runtime
- Use environment variables for configuration (no hardcoded values)
- Implement structured logging with trace IDs
- Include error handling and retries
- PII redaction in all logs

### Data Schema Standards
- **Email Processing Table** (DynamoDB): PK = `email_id` (UUID)
- **Model Performance Table**: PK = `task_type`, SK = `model_id#timestamp`
- **Knowledge Base Embeddings**: PK = `doc_id`, includes vector embedding as list
- All timestamps in ISO 8601 format
- All JSON outputs must include `confidence_score` (0-1)

### AI/ML Conventions
- **RAG chunking**: 500 tokens per chunk, 50 token overlap
- **Confidence thresholds**: ≥0.8 auto-response, 0.5-0.8 review, <0.5 escalate
- **Bedrock model IDs**:
  - Claude 3 Sonnet: `anthropic.claude-3-sonnet-20240229-v1:0`
  - Claude 3 Haiku: `anthropic.claude-3-haiku-20240307-v1:0`
  - Titan Embeddings: `amazon.titan-embed-text-v1`
- Always log: model ID, tokens used, latency, confidence score, RAG references

## Development Workflow

### Phase 1: Infrastructure Foundation
1. Create Terraform backend (S3 + DynamoDB state lock)
2. Build modular Terraform structure for all AWS resources
3. Deploy and validate base infrastructure

### Phase 2: Core Pipeline
1. Implement email parsing Lambda
2. Build RAG knowledge base (ingestion + retrieval)
3. Create Claude 3 response generation Lambda
4. Define Step Functions state machine
5. Wire up end-to-end pipeline

### Phase 3: Evaluation & Observability
1. Implement multi-LLM benchmarking
2. Build evaluation metrics system
3. Set up CloudWatch metrics and alerts
4. Create unified logging framework

### Phase 4: Dashboard
1. Build backend API (Lambda + API Gateway)
2. Create React frontend
3. Deploy to S3 + CloudFront
4. Integrate authentication (Cognito)
