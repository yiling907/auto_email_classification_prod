# InsureMail AI

AI-powered automated email response system for insurance companies.

## Overview

InsureMail AI uses AWS Bedrock (Claude 3 Sonnet) with RAG to automatically process and respond to insurance emails with high confidence and full traceability. The system classifies incoming emails into 17 intent categories, routes them to 12 specialist teams, and generates grounded replies using a knowledge base of policy documents.

## Architecture

- **Cloud**: AWS (Bedrock, Lambda, Step Functions, S3, DynamoDB, API Gateway, CloudWatch)
- **IaC**: Terraform
- **AI**: Claude 3 Sonnet (primary) + Multi-LLM evaluation (Mistral 7B, Llama 3.1 8B)
- **Language**: Python 3.11+
- **Dashboard**: React
- **Email**: Amazon SES (bidirectional)

## Features

- **AI-Powered Classification** — 17-intent classification with 12 routing teams
- **Confidence-Based Routing** — auto-respond >=0.8, human review 0.5-0.8, escalate <0.5
- **RAG Knowledge Base** — 320+ chunks across 177+ source files
- **Multi-LLM Benchmarking** — Mistral 7B and Llama 3.1 8B evaluation
- **Web Dashboard** — 6 pages: Overview, Emails, Email Detail, Model Performance, RAG Metrics, Evaluations
- **Model Settings** — toggle between Mistral 7B and Llama 3.1 8B at runtime
- **Editable Responses** — review and edit AI-generated replies before sending
- **Full Traceability** — complete audit trail for every email

## Cost

**Monthly estimates:**
- 100 emails/day: **~$2/month**
- 1,000 emails/day: **~$19/month**
- 10,000 emails/day: **~$179/month**

## Quick Start

### Prerequisites
- AWS Account with Bedrock access (Claude 3 Sonnet, Titan Embeddings)
- Terraform >= 1.0
- Python >= 3.11
- Node.js >= 18 (for dashboard)

### Deployment

1. Configure AWS credentials:
```bash
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
```

2. Set up email integration:
```bash
bash scripts/setup_ses.sh
```

3. Deploy infrastructure:
```bash
cd terraform && terraform init && terraform apply
```

4. Deploy Lambda functions:
```bash
bash scripts/deploy_lambdas.sh --all
```

5. Deploy dashboard:
```bash
bash scripts/deploy_dashboard.sh
```

## Documentation

- **[DEVELOPMENT.md](DEVELOPMENT.md)** — Developer guide (project structure, API reference, schemas, gotchas)
- **[DEPLOY.md](DEPLOY.md)** — Deployment guide (full deploy, incremental Lambda updates, rollback)
- **[CLAUDE.md](CLAUDE.md)** — Development guidance for Claude Code
- **[tests/README.md](tests/README.md)** — Testing guide
- **[dashboard/README.md](dashboard/README.md)** — Dashboard setup and features

## License

MIT
