#!/usr/bin/env bash
# =============================================================================
# InsureMail AI — Lint Script
# Runs Python (ruff/flake8) and JS (eslint) linters.
# Usage: ./scripts/lint/lint.sh [--target python|js|all]
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_PATH="${VENV_PATH:-$PROJECT_ROOT/venv}"
TARGET="${TARGET:-all}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/lint_$TIMESTAMP.log"
EXIT_CODE=0

while [[ $# -gt 0 ]]; do
  case $1 in
    --target) TARGET="$2"; shift 2 ;;
    *) echo "[ERROR] Unknown argument: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"
echo "[$(date -u +%FT%TZ)] LINT START — target=$TARGET" | tee -a "$LOG_FILE"

[[ -f "$VENV_PATH/bin/activate" ]] && source "$VENV_PATH/bin/activate"

lint_python() {
  echo "[INFO] Linting Python..." | tee -a "$LOG_FILE"
  cd "$PROJECT_ROOT"
  if command -v ruff &>/dev/null; then
    ruff check lambda/ scripts/ tests/ 2>&1 | tee -a "$LOG_FILE" || EXIT_CODE=1
  elif command -v flake8 &>/dev/null; then
    flake8 lambda/ scripts/ tests/ --max-line-length 100 2>&1 | tee -a "$LOG_FILE" || EXIT_CODE=1
  else
    echo "[WARN] No Python linter found (install ruff or flake8)" | tee -a "$LOG_FILE"
  fi
}

lint_js() {
  echo "[INFO] Linting JavaScript..." | tee -a "$LOG_FILE"
  cd "$PROJECT_ROOT/dashboard/frontend"
  npm run lint 2>&1 | tee -a "$LOG_FILE" || EXIT_CODE=1
}

case "$TARGET" in
  python) lint_python ;;
  js)     lint_js ;;
  all)    lint_python; lint_js ;;
  *) echo "[ERROR] Unknown target: $TARGET"; exit 1 ;;
esac

if [[ $EXIT_CODE -eq 0 ]]; then
  echo "[$(date -u +%FT%TZ)] LINT PASSED" | tee -a "$LOG_FILE"
else
  echo "[$(date -u +%FT%TZ)] LINT FAILED" | tee -a "$LOG_FILE"
fi
echo "[INFO] Log: $LOG_FILE"
exit $EXIT_CODE
