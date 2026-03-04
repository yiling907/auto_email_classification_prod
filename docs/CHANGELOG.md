# Changelog

All notable changes to InsureMail AI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- VPC configuration for Lambda functions
- AWS Secrets Manager integration
- CI/CD pipeline with GitHub Actions
- Custom domain setup for SES receiving
- Performance optimization and caching
- A/B testing framework for model selection

---

## [1.0.0] - 2026-03-04

### Added

#### Core Features
- **End-to-end email processing pipeline** using AWS Step Functions
- **Multi-LLM inference** with Mistral 7B and Llama 3.1 8B
- **RAG (Retrieval-Augmented Generation)** with Titan Embeddings
- **Confidence-based routing** (auto-respond ≥0.8, review 0.5-0.8, escalate <0.5)
- **Real-time metrics collection** and evaluation
- **Dashboard** with React frontend (overview, email trace, model comparison)

#### Infrastructure
- Complete Terraform infrastructure as code
- 9 Lambda functions for core processing
- DynamoDB tables for emails, metrics, and embeddings
- S3 buckets for emails, knowledge base, and logs
- Step Functions workflow orchestration
- EventBridge rules for scheduled metrics collection
- CloudWatch logging and monitoring
- SNS topic for SES email notifications

#### Email Integration
- Amazon SES receiving configuration
- Email parsing with PII redaction
- Automated response generation
- Email sending via SES

#### Testing
- **100+ unit tests** with pytest and moto
- **10+ integration tests** for end-to-end workflows
- **16+ Terraform validation tests**
- **83% code coverage** (target 70%+)
- CI/CD pipeline with GitHub Actions
- Automated test runner (Makefile + scripts)

#### Documentation
- Complete deployment guide (infrastructure + dashboard)
- SES setup and configuration guide
- RAG knowledge base setup guide
- Cost optimization analysis
- Troubleshooting guide with common issues
- Testing implementation documentation
- Project roadmap

#### Cost Optimization
- Switched from Claude 3 to open-source models (Mistral 7B)
- Cost reduced from $21/month to $13-18/month for 1,000 emails/day
- 100% open-source model stack for core processing

#### Developer Tools
- Email workflow simulation script (bypasses SES for testing)
- SES setup automation script
- Knowledge base upload script
- Test data generation
- CloudWatch log streaming helpers

### Fixed

#### Critical Bugs
- **DynamoDB float type error** - Converting floats to Decimal for DynamoDB storage
- **RAG embedding storage** - Serialize float arrays as JSON strings
- **Evaluation metrics integration** - Lambda not being invoked, added EventBridge triggers
- **API response format** - Fixed double-wrapped JSON responses
- **Model configuration errors** - Updated to use inference profiles for Llama 3.1 8B
- **Deprecated models** - Removed Titan Text Express (EOL)

#### Infrastructure
- S3 event triggers for automatic RAG ingestion
- IAM permissions for Lambda-to-Lambda invocation
- IAM permissions for Bedrock inference profiles
- SNS topic subscription for email receiver Lambda

### Changed

#### Model Configuration
- **Primary model**: Mistral 7B Instruct (cost-optimized)
- **Fallback model**: Llama 3.1 8B (using inference profile)
- **Embeddings**: Amazon Titan Embeddings (maintained)
- Removed deprecated Titan Text Express model

#### Architecture
- Evaluation metrics now runs on EventBridge schedule (daily/weekly)
- API handlers delegate to evaluation_metrics Lambda
- RAG documents auto-process on S3 upload

### Deprecated
- Amazon Titan Text Express (reached EOL)
- Direct API calls to evaluation_metrics (now via Lambda)

### Removed
- Hardcoded float values in DynamoDB writes
- Unused CLAUDE_MODEL_ID variable reference

### Security
- IAM least-privilege policies for all Lambda functions
- S3 bucket encryption at rest
- DynamoDB encryption enabled
- PII redaction in CloudWatch logs
- Public access blocks on S3 buckets

---

## [0.3.0] - 2026-03-03

### Added
- Comprehensive testing framework (100+ tests)
- GitHub Actions CI/CD pipeline
- Test coverage reporting (83%)
- Automated linting and security scanning

### Fixed
- Model metrics storage bug (DynamoDB float type)
- API response format for model performance endpoint

---

## [0.2.0] - 2026-03-02

### Added
- Real email integration with Amazon SES
- Email sending capability
- Dashboard frontend (React)
- API Gateway endpoints
- Evaluation metrics Lambda function
- EventBridge scheduled triggers

### Changed
- Switched to cost-optimized models (Mistral 7B)
- Enhanced RAG retrieval logic

---

## [0.1.0] - 2026-03-01

### Added
- Initial Terraform infrastructure
- Core Lambda functions (email parser, RAG, Claude response)
- Step Functions workflow
- DynamoDB tables and S3 buckets
- Basic RAG implementation with Titan Embeddings
- CloudWatch monitoring
- Project documentation

---

## Version History

- **1.0.0** (2026-03-04): Production-ready release with testing, documentation, and bug fixes
- **0.3.0** (2026-03-03): Testing framework and CI/CD
- **0.2.0** (2026-03-02): Email integration and dashboard
- **0.1.0** (2026-03-01): Initial infrastructure and core features

---

## Release Notes Format

Each release includes:
- **Added**: New features
- **Changed**: Changes to existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security improvements

---

## Upgrade Notes

### Upgrading to 1.0.0

1. **Update Terraform**:
   ```bash
   cd terraform
   terraform init -upgrade
   terraform plan
   terraform apply
   ```

2. **Redeploy Lambda functions** (includes bug fixes):
   ```bash
   terraform apply -target=module.lambda
   ```

3. **Verify evaluation metrics**:
   ```bash
   aws lambda invoke \
     --function-name insuremail-ai-dev-evaluation-metrics \
     --payload '{"task_type":"all","days":7}' \
     output.json
   ```

4. **Update dashboard** (if deployed):
   ```bash
   ./scripts/deploy_dashboard.sh
   ```

### Breaking Changes

None in 1.0.0 release.

---

## Support

For issues or questions:
- Check [TROUBLESHOOTING.md](./troubleshooting/TROUBLESHOOTING.md)
- Review CloudWatch logs
- See [Deployment Guide](./guides/DEPLOYMENT.md)

---

**Last Updated**: March 4, 2026
