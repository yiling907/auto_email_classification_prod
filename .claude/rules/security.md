# Security Rules for Claude Code

## 1. Default-Deny Policy
All actions not explicitly whitelisted in `settings.json` are denied.
When in doubt, do NOT proceed — ask the user for confirmation.

## 2. Filesystem Boundaries
- **Allowed**: Read/write within `/Users/leiyiling/IdeaProjects/auto_email_classification_prod/`
- **Denied**: Access to `~/.ssh`, `~/.aws`, `/etc`, `/var`, `/usr`, `/sys`
- **Denied**: Files matching `*.env`, `*secret*`, `*password*`, `*credential*`, `*.pem`, `*.key`
- **Denied**: `node_modules/`, `.git/` internals (use git CLI instead)

## 3. Command Safety
### Auto-allowed (safe reads)
`ls`, `cat`, `git status`, `git diff`, `git log`, `pytest`, `npm run lint`, `make test`

### Require user confirmation
`npm install`, `pip install`, `pip3 install`, `terraform apply`, `terraform destroy`
Any `rm` command, any `sudo` command, any AWS resource-mutating command

### Always forbidden
`rm -rf`, `sudo su`, `curl | bash`, `wget | sh`, `chmod 777`
Any command that reads `.env` or secret files directly

## 4. AWS Operations
### Auto-allowed (read-only)
`aws s3 ls`, `aws lambda get-*`, `aws lambda list-*`,
`aws stepfunctions describe-*`, `aws stepfunctions list-*`,
`aws dynamodb scan`, `aws dynamodb query`, `aws dynamodb get-item`,
`aws cloudwatch get-*`, `aws cloudwatch list-*`

### Require Terraform (never run directly)
Resource creation, modification, deletion — use `terraform apply` with user approval.
- NEVER run: `aws ec2 run-instances`, `aws rds create-*`, `aws iam create-*`
- NEVER run: `aws dynamodb delete-table`, `aws s3 rb`, `aws lambda delete-*`

### High-risk — require explicit approval
`terraform apply`, `terraform destroy` — must show plan output first and get user sign-off

## 5. Network Access
Trusted domains for WebFetch:
- `docs.anthropic.com`
- `boto3.amazonaws.com`
- `registry.terraform.io`
- `www.trulens.org`
- `python.langchain.com`

All other domains require user confirmation before fetching.

## 6. Script Generation Rules
- All generated scripts go in `/scripts/[type]/` (e.g., `/scripts/deploy/deploy.sh`)
- Scripts must be generic and configurable (no hardcoded values)
- Scripts must include: logging, error handling, entry/exit codes
- For duplicate task types: ask user — UPDATE existing or CREATE versioned (e.g., `deploy_v2.sh`)

## 7. Secrets Handling
- NEVER read, print, log, or commit: `.env`, `terraform.tfvars`, `*.pem`, `*_key*`
- NEVER hardcode credentials, tokens, or ARNs in scripts
- Use environment variables or AWS Secrets Manager references only

## 8. Audit
All tool calls and Bash executions are logged by Claude Code automatically.
For production operations, always note the action taken in the commit message.
