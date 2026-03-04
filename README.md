# InsureMail AI

AI-powered automated email response system for insurance companies.

## Overview

InsureMail AI uses AWS Bedrock (Claude 3) with RAG to automatically process and respond to insurance emails with high confidence and full traceability.

## Architecture

- **Cloud**: AWS (Bedrock, Lambda, Step Functions, S3, DynamoDB)
- **IaC**: Terraform
- **AI**: Claude 3 Haiku (cost-optimized) + Multi-LLM evaluation
- **Language**: Python 3.11+
- **Dashboard**: React
- **Email**: Amazon SES (bidirectional)

## Features

✅ **Real Email Integration** - Receive and send emails via Amazon SES
✅ **AI-Powered Responses** - Claude 3 Haiku with RAG knowledge base
✅ **High Confidence Routing** - Auto-respond (≥0.8), review (0.5-0.8), escalate (<0.5)
✅ **Full Traceability** - Complete audit trail for every email
✅ **Multi-LLM Benchmarking** - Compare model performance
✅ **Web Dashboard** - Real-time monitoring and analytics
✅ **Cost-Optimized** - ~$19/month for 1,000 emails/day

## Cost

**Monthly estimates:**
- 100 emails/day: **~$2/month**
- 1,000 emails/day: **~$19/month**
- 10,000 emails/day: **~$179/month**

See [COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) for details.

## Quick Start

### Prerequisites
- AWS Account with Bedrock access (Claude 3 Haiku, Titan Embeddings)
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
./scripts/setup_ses.sh
```

3. Deploy infrastructure:
```bash
cd terraform
terraform init
terraform apply
```

4. Deploy dashboard:
```bash
./scripts/deploy_dashboard.sh
```

## Documentation

### Setup Guides
- [SES_SETUP.md](docs/SES_SETUP.md) - Email integration setup
- [EMAIL_INTEGRATION.md](docs/EMAIL_INTEGRATION.md) - Email configuration guide
- [DEPLOY_TO_AWS.md](docs/DEPLOY_TO_AWS.md) - Dashboard deployment

### Technical Docs
- [CLAUDE.md](CLAUDE.md) - Development guidance for Claude Code
- [COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) - Cost optimization strategies
- [DASHBOARD_GUIDE.md](docs/DASHBOARD_GUIDE.md) - Dashboard features
- [ROADMAP.md](docs/ROADMAP.md) - Future enhancements

### Project Specs
- [claude.md](claude.md) - Full project specification

## License

MIT
