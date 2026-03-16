#!/usr/bin/env bash
# =============================================================================
# InsureMail AI — Debug Script
# Tails CloudWatch logs or invokes a Lambda with a test payload.
# Usage: ./scripts/debug/debug.sh [--lambda <name>] [--payload '{"key":"val"}']
#        ./scripts/debug/debug.sh [--logs <lambda-name>] [--tail 100]
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV="${ENV:-dev}"
MODE="${MODE:-logs}"          # logs | invoke
LAMBDA_NAME="${LAMBDA_NAME:-}"
PAYLOAD="${PAYLOAD:-{}}"
TAIL_LINES="${TAIL_LINES:-50}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/debug_$TIMESTAMP.log"

while [[ $# -gt 0 ]]; do
  case $1 in
    --lambda)  LAMBDA_NAME="$2"; MODE="invoke"; shift 2 ;;
    --logs)    LAMBDA_NAME="$2"; MODE="logs";   shift 2 ;;
    --payload) PAYLOAD="$2";     shift 2 ;;
    --tail)    TAIL_LINES="$2";  shift 2 ;;
    --env)     ENV="$2";         shift 2 ;;
    *) echo "[ERROR] Unknown argument: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"
echo "[$(date -u +%FT%TZ)] DEBUG START — mode=$MODE lambda=$LAMBDA_NAME" | tee -a "$LOG_FILE"

FULL_NAME="insuremail-ai-${ENV}-${LAMBDA_NAME}"

case "$MODE" in
  invoke)
    [[ -n "$LAMBDA_NAME" ]] || { echo "[ERROR] --lambda required for invoke mode"; exit 1; }
    RESPONSE_FILE="/tmp/lambda_response_$TIMESTAMP.json"
    echo "[INFO] Invoking $FULL_NAME with payload: $PAYLOAD" | tee -a "$LOG_FILE"
    aws lambda invoke \
      --function-name "$FULL_NAME" \
      --payload "$PAYLOAD" \
      --cli-binary-format raw-in-base64-out \
      --log-type Tail \
      --no-cli-pager \
      "$RESPONSE_FILE" 2>&1 | tee -a "$LOG_FILE"
    echo "[INFO] Response:" | tee -a "$LOG_FILE"
    cat "$RESPONSE_FILE" | python3 -m json.tool 2>/dev/null || cat "$RESPONSE_FILE"
    ;;

  logs)
    [[ -n "$LAMBDA_NAME" ]] || { echo "[ERROR] --logs requires a Lambda name"; exit 1; }
    LOG_GROUP="/aws/lambda/$FULL_NAME"
    echo "[INFO] Fetching recent logs from $LOG_GROUP (last $TAIL_LINES lines)" | tee -a "$LOG_FILE"
    # Get most recent log stream
    STREAM=$(aws logs describe-log-streams \
      --log-group-name "$LOG_GROUP" \
      --order-by LastEventTime --descending \
      --max-items 1 \
      --query 'logStreams[0].logStreamName' \
      --output text)
    echo "[INFO] Stream: $STREAM" | tee -a "$LOG_FILE"
    aws logs get-log-events \
      --log-group-name "$LOG_GROUP" \
      --log-stream-name "$STREAM" \
      --limit "$TAIL_LINES" \
      --no-cli-pager \
      --query 'events[*].message' \
      --output text 2>&1 | tee -a "$LOG_FILE"
    ;;

  *) echo "[ERROR] Unknown mode: $MODE"; exit 1 ;;
esac

echo "[$(date -u +%FT%TZ)] DEBUG COMPLETE" | tee -a "$LOG_FILE"
echo "[INFO] Log: $LOG_FILE"
