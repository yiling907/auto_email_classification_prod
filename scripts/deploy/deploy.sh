#!/usr/bin/env bash
# =============================================================================
# InsureMail AI — Deploy Script
# Deploys Lambda functions and/or the React dashboard to AWS.
# Usage: ./scripts/deploy/deploy.sh [--target lambda|dashboard|all] [--env dev|prod]
#
# SAFETY: Does NOT run terraform apply. Infrastructure changes must go via Terraform.
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="${TARGET:-dashboard}"
ENV="${ENV:-dev}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/deploy_${TARGET}_${ENV}_$TIMESTAMP.log"

# ── S3 / CloudFront config (set via env or defaults) ─────────────────────────
DASHBOARD_BUCKET="${DASHBOARD_BUCKET:-insuremail-ai-dashboard}"
CLOUDFRONT_DIST_ID="${CLOUDFRONT_DIST_ID:-E2ADYLCS9LNMWF}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --target) TARGET="$2"; shift 2 ;;
    --env)    ENV="$2";    shift 2 ;;
    *) echo "[ERROR] Unknown argument: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"
echo "[$(date -u +%FT%TZ)] DEPLOY START — target=$TARGET env=$ENV" | tee -a "$LOG_FILE"

# ── Safety check ─────────────────────────────────────────────────────────────
if [[ "$ENV" == "prod" ]]; then
  echo "[WARN] Deploying to PRODUCTION. Confirm? (yes/no)"
  read -r confirm
  [[ "$confirm" == "yes" ]] || { echo "[ABORT] Deploy cancelled."; exit 1; }
fi

deploy_lambda() {
  local name="$1"
  local zip="$PROJECT_ROOT/dist/${name}.zip"
  if [[ ! -f "$zip" ]]; then
    echo "[ERROR] Missing zip: $zip — run build.sh first"; exit 1
  fi
  echo "[INFO] Deploying Lambda: $name" | tee -a "$LOG_FILE"
  aws lambda update-function-code \
    --function-name "insuremail-ai-${ENV}-${name}" \
    --zip-file "fileb://$zip" \
    --no-cli-pager 2>&1 | tee -a "$LOG_FILE"
  echo "[INFO]   Lambda $name deployed." | tee -a "$LOG_FILE"
}

deploy_dashboard() {
  local dist_dir="$PROJECT_ROOT/dashboard/frontend/dist"
  [[ -d "$dist_dir" ]] || { echo "[ERROR] No dist/ — run build.sh first"; exit 1; }
  echo "[INFO] Syncing dashboard to s3://$DASHBOARD_BUCKET" | tee -a "$LOG_FILE"
  aws s3 sync "$dist_dir" "s3://$DASHBOARD_BUCKET" --delete 2>&1 | tee -a "$LOG_FILE"
  echo "[INFO] Invalidating CloudFront ($CLOUDFRONT_DIST_ID)" | tee -a "$LOG_FILE"
  aws cloudfront create-invalidation \
    --distribution-id "$CLOUDFRONT_DIST_ID" \
    --paths "/*" \
    --no-cli-pager 2>&1 | tee -a "$LOG_FILE"
  echo "[INFO] Dashboard deployed." | tee -a "$LOG_FILE"
}

case "$TARGET" in
  dashboard)
    deploy_dashboard
    ;;
  lambda)
    for dir in "$PROJECT_ROOT"/lambda/*/; do
      deploy_lambda "$(basename "$dir")"
    done
    ;;
  all)
    for dir in "$PROJECT_ROOT"/lambda/*/; do
      deploy_lambda "$(basename "$dir")"
    done
    deploy_dashboard
    ;;
  *) echo "[ERROR] Unknown target: $TARGET"; exit 1 ;;
esac

echo "[$(date -u +%FT%TZ)] DEPLOY COMPLETE" | tee -a "$LOG_FILE"
echo "[INFO] Log: $LOG_FILE"
