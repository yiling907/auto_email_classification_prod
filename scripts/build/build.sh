#!/usr/bin/env bash
# =============================================================================
# InsureMail AI — Build Script
# Builds Lambda zips and/or the React dashboard.
# Usage: ./scripts/build/build.sh [--target lambda|dashboard|all]
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="${TARGET:-all}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build_$TIMESTAMP.log"

while [[ $# -gt 0 ]]; do
  case $1 in
    --target) TARGET="$2"; shift 2 ;;
    *) echo "[ERROR] Unknown argument: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"
echo "[$(date -u +%FT%TZ)] BUILD START — target=$TARGET" | tee -a "$LOG_FILE"

build_lambdas() {
  echo "[INFO] Building Lambda packages..." | tee -a "$LOG_FILE"
  cd "$PROJECT_ROOT"
  for dir in lambda/*/; do
    name="$(basename "$dir")"
    zip_path="$PROJECT_ROOT/dist/${name}.zip"
    mkdir -p "$PROJECT_ROOT/dist"
    echo "[INFO]   Packaging $name → $zip_path" | tee -a "$LOG_FILE"
    # Install deps into a tmp layer dir if requirements.txt exists
    if [[ -f "$dir/requirements.txt" ]]; then
      pip3 install -r "$dir/requirements.txt" -t "$dir/package/" -q
      (cd "$dir/package" && zip -r "$zip_path" . -q)
    fi
    (cd "$dir" && zip -r "$zip_path" lambda_function.py -u -q)
    echo "[INFO]   Done: $zip_path" | tee -a "$LOG_FILE"
  done
}

build_dashboard() {
  echo "[INFO] Building React dashboard..." | tee -a "$LOG_FILE"
  cd "$PROJECT_ROOT/dashboard/frontend"
  npm run build 2>&1 | tee -a "$LOG_FILE"
  echo "[INFO] Dashboard built: dashboard/frontend/dist/" | tee -a "$LOG_FILE"
}

case "$TARGET" in
  lambda)    build_lambdas ;;
  dashboard) build_dashboard ;;
  all)       build_lambdas; build_dashboard ;;
  *) echo "[ERROR] Unknown target: $TARGET"; exit 1 ;;
esac

echo "[$(date -u +%FT%TZ)] BUILD COMPLETE" | tee -a "$LOG_FILE"
echo "[INFO] Log: $LOG_FILE"
