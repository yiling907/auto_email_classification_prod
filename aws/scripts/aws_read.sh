#!/usr/bin/env bash
# =============================================================================
# InsureMail AI — AWS Read-Only Diagnostics (safe, auto-allowed)
# Collects a snapshot of live infrastructure state for debugging/reporting.
# Usage: ./aws/scripts/aws_read.sh [--env dev|prod]
# =============================================================================
set -euo pipefail

ENV="${ENV:-dev}"
PREFIX="insuremail-ai-${ENV}"
LOG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/aws_read_$TIMESTAMP.log"

while [[ $# -gt 0 ]]; do
  case $1 in
    --env) ENV="$2"; PREFIX="insuremail-ai-${ENV}"; shift 2 ;;
    *) echo "[ERROR] Unknown argument: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo " InsureMail AI — AWS State Snapshot"
echo " Env: $ENV  |  $(date -u +%FT%TZ)"
echo "=========================================="

echo -e "\n--- Lambda Functions ---"
aws lambda list-functions \
  --query "Functions[?starts_with(FunctionName,'$PREFIX')].{Name:FunctionName,Runtime:Runtime,Modified:LastModified}" \
  --output table --no-cli-pager

echo -e "\n--- Step Functions ---"
aws stepfunctions list-state-machines \
  --query "stateMachines[?contains(name,'$PREFIX')].{Name:name,ARN:stateMachineArn}" \
  --output table --no-cli-pager

echo -e "\n--- Recent Step Function Executions ---"
SFN_ARN=$(aws stepfunctions list-state-machines \
  --query "stateMachines[?contains(name,'$PREFIX-email')].stateMachineArn" \
  --output text --no-cli-pager 2>/dev/null | head -1)
if [[ -n "$SFN_ARN" ]]; then
  aws stepfunctions list-executions \
    --state-machine-arn "$SFN_ARN" \
    --max-results 10 \
    --query "executions[*].{Name:name,Status:status,Start:startDate}" \
    --output table --no-cli-pager
fi

echo -e "\n--- DynamoDB Tables ---"
aws dynamodb list-tables \
  --query "TableNames[?contains(@,'$PREFIX')]" \
  --output table --no-cli-pager

echo -e "\n--- S3 Buckets ---"
aws s3 ls | grep "insuremail" || echo "(none found)"

echo -e "\n=========================================="
echo " Snapshot complete — Log: $LOG_FILE"
echo "=========================================="
