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

📚 **Complete documentation index**: [docs/README.md](docs/README.md)

### Quick Links

#### Getting Started
- **[Deployment Guide](docs/guides/DEPLOYMENT.md)** - Complete setup (infrastructure + dashboard)
- **[Testing Guide](tests/README.md)** - Running tests and validation
- **[Troubleshooting](docs/troubleshooting/TROUBLESHOOTING.md)** - Common issues and solutions

#### Configuration
- **[SES Setup](docs/guides/SES_SETUP.md)** - Email integration
- **[RAG Setup](docs/guides/RAG_SETUP.md)** - Knowledge base configuration
- **[Dashboard Guide](docs/guides/DASHBOARD_GUIDE.md)** - Dashboard features

#### Reference
- **[Cost Optimization](docs/reference/COST_OPTIMIZATION.md)** - Cost analysis and strategies
- **[Open Source Models](docs/reference/OPEN_SOURCE_MODELS.md)** - Model comparison
- **[Architecture](docs/reference/MODEL_METRICS_DATA_FLOW.md)** - System architecture

#### Developer Resources
- **[CLAUDE.md](CLAUDE.md)** - Development guidance for Claude Code
- **[ROADMAP.md](docs/ROADMAP.md)** - Future enhancements
- **[CHANGELOG.md](docs/CHANGELOG.md)** - Release history

## License

MIT
