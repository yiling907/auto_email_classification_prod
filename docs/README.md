# InsureMail AI Documentation

Complete documentation for the InsureMail AI automated email processing system.

---

## 📚 Getting Started

New to the project? Start here:

1. **[Main README](../README.md)** - Project overview and quick start
2. **[Deployment Guide](#deployment)** - Step-by-step setup instructions
3. **[Testing Guide](../tests/README.md)** - Running tests and validation

---

## 🚀 Deployment

### Setup Guides
- **[DEPLOYMENT.md](./guides/DEPLOYMENT.md)** - Complete deployment guide (infrastructure + dashboard)
- **[SES_SETUP.md](./guides/SES_SETUP.md)** - Email integration setup
- **[RAG_SETUP.md](./guides/RAG_SETUP.md)** - Knowledge base configuration

### Configuration
- **[COST_OPTIMIZATION.md](./reference/COST_OPTIMIZATION.md)** - Cost analysis and optimization strategies
- **[OPEN_SOURCE_MODELS.md](./reference/OPEN_SOURCE_MODELS.md)** - Model comparison and selection

---

## 📖 Reference Documentation

### Architecture
- **[ARCHITECTURE.md](./reference/ARCHITECTURE.md)** - System architecture and data flow
- **[MODEL_METRICS_DATA_FLOW.md](./reference/MODEL_METRICS_DATA_FLOW.md)** - Metrics collection and storage

### Features
- **[DASHBOARD_GUIDE.md](./guides/DASHBOARD_GUIDE.md)** - Dashboard features and usage
- **[EMAIL_INTEGRATION.md](./guides/EMAIL_INTEGRATION.md)** - Email receiving and sending setup

---

## 🐛 Troubleshooting

### Known Issues
- **[TROUBLESHOOTING.md](./troubleshooting/TROUBLESHOOTING.md)** - Common issues and solutions
- **[SES_LIMITATIONS.md](./troubleshooting/SES_LIMITATIONS.md)** - SES receiving limitations (Gmail-to-Gmail)

### Historical Bug Fixes
- **[METRICS_STORAGE_BUG_FIX.md](./historical/METRICS_STORAGE_BUG_FIX.md)** - DynamoDB float type bug
- **[EVALUATION_METRICS_INTEGRATION.md](./historical/EVALUATION_METRICS_INTEGRATION.md)** - Metrics integration details

---

## 📊 Project Status

- **[ROADMAP.md](./ROADMAP.md)** - Future enhancements and planned features
- **[CHANGELOG.md](./CHANGELOG.md)** - Release history and updates

---

## 🔍 Quick Reference

### Common Commands

```bash
# Deploy infrastructure
cd terraform && terraform apply

# Run tests
make test

# Deploy dashboard
./scripts/deploy_dashboard.sh

# Simulate email workflow (testing)
bash scripts/simulate_email_workflow.sh

# Check metrics
aws lambda invoke --function-name insuremail-ai-dev-evaluation-metrics \
  --payload '{"task_type":"all","days":7}' output.json
```

### Important Links

- **Dashboard**: http://insuremail-ai-dashboard.s3-website-us-east-1.amazonaws.com
- **API Gateway**: Check `terraform output api_gateway_url`
- **CloudWatch Logs**: `/aws/lambda/insuremail-ai-dev-*`

---

## 📝 Documentation Status

### ✅ Complete
- Infrastructure deployment
- Email integration (SES)
- RAG knowledge base
- Testing framework
- Cost optimization
- Dashboard deployment

### ⏳ In Progress
- Troubleshooting guide consolidation
- API reference documentation

### 📅 Planned
- Video tutorials
- Architecture diagrams
- Performance tuning guide

---

## 🤝 Contributing

When adding new documentation:

1. **Place in correct category**:
   - `guides/` - How-to instructions
   - `reference/` - Technical specifications
   - `troubleshooting/` - Problem-solving guides
   - `historical/` - Bug fixes and integration notes

2. **Update this index** - Add link to new doc in appropriate section

3. **Follow naming conventions**:
   - Use UPPERCASE for markdown files
   - Use descriptive names (GOOD: `SES_SETUP.md`, BAD: `setup.md`)
   - Include dates for historical docs

4. **Cross-reference** - Link related docs together

---

## 📧 Support

- **Technical Issues**: Check CloudWatch logs first
- **Documentation Issues**: Update docs directly via PR
- **Feature Requests**: See [ROADMAP.md](./ROADMAP.md)

---

**Last Updated**: March 4, 2026
**Project Status**: Production-ready (SES sandbox mode)
