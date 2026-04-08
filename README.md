# InsureMail AI

AI-powered automated email processing and auto-response system for insurance companies.

## Overview

InsureMail AI uses AWS Bedrock foundation models with hybrid RAG to automatically process and respond to customer emails with high confidence and full traceability. The system parses emails (including PDF/DOCX attachments), extracts entities, classifies intents with an ensemble classifier, retrieves relevant knowledge from internal policy documents, validates customer/policy data against CRM, assesses fraud risk, generates personalized replies, and routes based on confidence: auto-respond (≥0.8), human review (0.5-0.8), or escalate (<0.5).

Classifies into **17 insurance intent categories** and routes to 12 specialist teams.

## Architecture

Workflow orchestrated by AWS Step Functions:

```
┌─────────────────────────────────────────────────────────────┐
│  ParseEmail: RFC parse, PII redaction, attachment extraction, entity extraction  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  ClassifyIntent: [LLM ∥ BioBERT] ensemble parallel classification  │
│  (Mistral 7B on Bedrock ∥ fine-tuned BioBERT on SageMaker)  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  RetrieveKnowledge: Hybrid RAG (HyDE + vector + BM25 + RRF) │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  ValidateCRM: Text-to-SQL → DynamoDB customer/policy lookup  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  AssessFraudRisk: Rule-based fraud scoring                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  GenerateResponse: Mistral/Llama → grounded response + quality judge  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  DetermineAction: Confidence routing → [AutoRespond ∥ Review ∥ Escalate]  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  SaveResult: Persist full execution trace to DynamoDB        │
└─────────────────────────────────────────────────────────────┘
```

**Tech Stack:**
- **Cloud**: AWS (Bedrock, Lambda, Step Functions, S3, DynamoDB, API Gateway, CloudWatch, SES)
- **IaC**: Terraform (modular)
- **AI**: Mistral 7B Instruct (primary), Llama 3.1 8B (fallback), Titan Embeddings V2 (RAG), BioBERT (ensemble classifier on SageMaker)
- **Language**: Python 3.11+ (Lambda), JavaScript/JSX (dashboard)
- **Dashboard**: React 18 + Vite (recently redesigned)
- **Email**: Amazon SES (incoming via SNS + outgoing auto-respond)

## Features

- **Ensemble Intent Classification** — LLM (Mistral 7B) + fine-tuned BioBERT run in parallel, 17 specialized insurance intent classes
- **Confidence-Based Routing** — auto-respond ≥0.8, human review 0.5–0.8, escalate <0.5
- **Hybrid RAG Retrieval** — HyDE query expansion + Titan vector search + BM25 + RRF fusion + cross-encoder re-ranking
- **Text-to-SQL CRM Validation** — LLM generates DynamoDB queries to validate customer/policy data automatically
- **Fraud Risk Assessment** — rule-based risk scoring before response generation
- **Multi-LLM Support** — toggle between Mistral 7B and Llama 3.1 8B at runtime
- **PII Redaction** — automatically redacts emails, phones, and IDs from logs for compliance
- **Graceful Fallbacks** — every step has error handling; pipeline never hard-fails, all errors escalate to human
- **Full Evaluation Suite** — Python scripts for end-to-end pipeline benchmarking
- **Redesigned React Dashboard** — browse all emails, view HTML-formatted details, check model metrics, approve/edit responses
- **Full Traceability** — complete execution trace persisted for every email in DynamoDB

## Features (continued)
- **Infrastructure as Code** — fully modular Terraform, everything provisioned automatically
- **SES + SNS Integration** — built-in support for incoming email via AWS SES receiving
- **Optional Gmail Polling** — Gmail IMAP poller alternative for non-SES setups

## Performance & Cost

**Accuracy (on Laya healthcare claims dataset):**
-  **>92%** intent classification accuracy with Mistral 7B

**Estimated monthly AWS cost:**
- 100 emails/day: **~$2–$5/month**
- 1,000 emails/day: **~$15–$25/month**
- 10,000 emails/day: **~$150–$200/month**

All services are pay-per-use serverless — no always-on resources.

## Quick Start

### Prerequisites
- AWS Account with Bedrock access enabled for:
  - `mistral.mistral-7b-instruct-v0:2`
  - `meta.llama3-8b-instruct-v1:0`
  - `amazon.titan-embed-text-v2:0`
- Terraform >= 1.0
- Python >= 3.11
- Node.js >= 18 (for dashboard)

### Deployment

1. Configure AWS credentials:
```bash
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1      # required
```

2. Initialize Terraform:
```bash
make tf-init
```

3. Review and apply Terraform:
```bash
make tf-plan
make tf-apply
```

4. Build and deploy Lambda layers and functions:
```bash
scripts/build/build.sh
make deploy-lambda
```

5. Load initial data (customers + knowledge base):
```bash
python scripts/load_customers.py
python scripts/load_knowledge_docs.py
```

6. Deploy dashboard (after `terraform output` gives you the bucket):
```bash
make dashboard-deploy
```

See `CLAUDE.md` for complete development commands.

## Documentation

- **[DEVELOPMENT.md](DEVELOPMENT.md)** — Developer guide (project structure, API reference, schemas, gotchas)
- **[DEPLOY.md](DEPLOY.md)** — Deployment guide (full deploy, incremental Lambda updates, rollback)
- **[CLAUDE.md](CLAUDE.md)** — Development guidance for Claude Code
- **[tests/README.md](tests/README.md)** — Testing guide
- **[dashboard/README.md](dashboard/README.md)** — Dashboard setup and features

## License

MIT
