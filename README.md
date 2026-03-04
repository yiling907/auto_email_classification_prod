# InsureMail AI

AI-powered automated email response system for insurance companies.

## Overview

InsureMail AI uses AWS Bedrock (Claude 3) with RAG to automatically process and respond to insurance emails with high confidence and full traceability.

## Architecture

- **Cloud**: AWS (Bedrock, Lambda, Step Functions, S3, DynamoDB)
- **IaC**: Terraform
- **AI**: Claude 3 (Sonnet/Haiku) + Multi-LLM evaluation
- **Language**: Python 3.11+
- **Dashboard**: React

## Quick Start

### Prerequisites
- AWS Account with Bedrock access (Claude 3, Titan, Llama 3, Mistral)
- Terraform >= 1.0
- Python >= 3.11
- Node.js >= 18 (for dashboard)

### Deployment

1. Configure AWS credentials:
```bash
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
```

2. Deploy infrastructure:
```bash
cd terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

3. Deploy dashboard:
```bash
cd dashboard/frontend
npm install
npm run build
./scripts/deploy_dashboard.sh
```

## Documentation

- [CLAUDE.md](CLAUDE.md) - Development guidance
- [claude.md](claude.md) - Full project specification

## License

MIT
