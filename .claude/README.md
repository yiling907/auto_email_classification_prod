# Claude Code — InsureMail AI Engineering Setup

## Overview
Enterprise Claude Code configuration for the InsureMail AI project.
Enforces security boundaries, script generation standards, and AWS/Terraform governance.

---

## Configuration Files

| File | Purpose |
|---|---|
| `settings.json` | Shared team permissions (committed to git) |
| `settings.local.json` | Personal/local permission overrides (git-ignored) |
| `rules/security.md` | Full security policy and command rules |

---

## Permission Model

```
Default: DENY ALL
    ↓
settings.json allow list  →  auto-approved
settings.json deny list   →  always blocked
everything else           →  prompt user
```

---

## Script Generation Workflow

When you give a task command (`deploy`, `test`, `build`, `debug`, `lint`):

1. Claude generates a reusable script (never runs it directly)
2. Script is placed in the appropriate folder:

```
scripts/
├── deploy/    deploy.sh, deploy_v2.sh ...
├── build/     build.sh ...
├── test/      test.sh ...
├── debug/     debug.sh ...
├── lint/      lint.sh ...
└── api/       claude_tool_api.py (RBAC middleware)

terraform/scripts/   Terraform automation scripts
aws/scripts/         AWS CLI read-only scripts
```

3. For duplicate task types, Claude asks: **UPDATE** existing or **CREATE** versioned?

---

## AWS & Terraform Rules

| Operation | Action |
|---|---|
| AWS read (`describe`, `list`, `get`, `ls`) | Auto-execute |
| AWS write (create, delete, modify) | **REJECTED** — use Terraform |
| `terraform init/fmt/validate/plan` | Auto-execute |
| `terraform apply / destroy` | **Requires your approval** |

---

## RBAC Tool API

`scripts/api/claude_tool_api.py` — production-grade Claude API client with:
- Role-based access control (admin / developer / readonly)
- Tool call permission middleware
- Structured audit logging
- Retry with exponential backoff

### Roles

| Role | Allowed Tools |
|---|---|
| `readonly` | `read_file`, `list_files`, `search_code` |
| `developer` | readonly + `write_file`, `run_tests`, `git_operations` |
| `admin` | developer + `deploy`, `manage_infrastructure`, `manage_secrets` |

### Usage
```python
from scripts.api.claude_tool_api import ClaudeToolClient, UserContext

client = ClaudeToolClient()
user = UserContext(user_id="dev-01", role="developer", team="backend")
response = client.run(user=user, prompt="Run the test suite and report results")
```

---

## Quick Reference

```bash
# Run assessment (safe — read + Step Functions)
source venv/bin/activate
python scripts/run_stepfn_assessment.py --sample 20 --trulens

# Run unit tests
pytest tests/unit/ -v

# Build + deploy dashboard
cd dashboard/frontend && npm run build
aws s3 sync dist s3://insuremail-ai-dashboard --delete
aws cloudfront create-invalidation --distribution-id E2ADYLCS9LNMWF --paths "/*"

# Terraform plan (safe)
cd terraform && terraform plan

# Terraform apply (REQUIRES APPROVAL — see rules/security.md)
cd terraform && terraform apply
```

---

## Team Onboarding

1. Clone the repo
2. Copy `.env.example` → `.env` and fill in values (never commit `.env`)
3. Run `source venv/bin/activate` to use the project Python environment
4. Claude Code picks up `settings.json` automatically — no extra setup needed
5. Read `rules/security.md` before running any infrastructure commands
