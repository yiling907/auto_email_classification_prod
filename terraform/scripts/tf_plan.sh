#!/usr/bin/env bash
# =============================================================================
# InsureMail AI — Terraform Plan (safe, auto-allowed)
# Usage: ./terraform/scripts/tf_plan.sh [--module modules/compute]
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_DIR="${TF_DIR:-$PROJECT_ROOT/terraform}"
MODULE="${MODULE:-}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/tf_plan_$TIMESTAMP.log"

while [[ $# -gt 0 ]]; do
  case $1 in
    --module) MODULE="$2"; shift 2 ;;
    *) echo "[ERROR] Unknown argument: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"
echo "[$(date -u +%FT%TZ)] TERRAFORM PLAN START" | tee -a "$LOG_FILE"

cd "${MODULE:+$TF_DIR/$MODULE}" 2>/dev/null || cd "$TF_DIR"

terraform fmt -recursive 2>&1 | tee -a "$LOG_FILE"
terraform validate         2>&1 | tee -a "$LOG_FILE"
terraform plan -out="$LOG_DIR/tfplan_$TIMESTAMP.binary" 2>&1 | tee -a "$LOG_FILE"

echo "[$(date -u +%FT%TZ)] PLAN COMPLETE — review above before applying" | tee -a "$LOG_FILE"
echo "[IMPORTANT] To apply, run: terraform apply $LOG_DIR/tfplan_$TIMESTAMP.binary"
echo "[INFO] Log: $LOG_FILE"
