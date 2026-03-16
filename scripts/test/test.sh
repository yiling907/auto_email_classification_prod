#!/usr/bin/env bash
# =============================================================================
# InsureMail AI — Test Runner
# Usage: ./scripts/test/test.sh [--path tests/unit] [--flags "-v -k test_rag"]
# =============================================================================
set -euo pipefail

# ── Config (override via env vars) ───────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_PATH="${VENV_PATH:-$PROJECT_ROOT/venv}"
TEST_PATH="${TEST_PATH:-tests/}"
PYTEST_FLAGS="${PYTEST_FLAGS:--v}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/test_$TIMESTAMP.log"

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --path)  TEST_PATH="$2"; shift 2 ;;
    --flags) PYTEST_FLAGS="$2"; shift 2 ;;
    *) echo "[ERROR] Unknown argument: $1"; exit 1 ;;
  esac
done

# ── Setup ────────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
echo "[$(date -u +%FT%TZ)] TEST START — path=$TEST_PATH flags=$PYTEST_FLAGS" | tee -a "$LOG_FILE"

# ── Activate venv ────────────────────────────────────────────────────────────
if [[ -f "$VENV_PATH/bin/activate" ]]; then
  source "$VENV_PATH/bin/activate"
  echo "[INFO] venv activated: $VENV_PATH" | tee -a "$LOG_FILE"
else
  echo "[WARN] No venv found at $VENV_PATH — using system Python" | tee -a "$LOG_FILE"
fi

# ── Run tests ────────────────────────────────────────────────────────────────
cd "$PROJECT_ROOT"
echo "[INFO] Running: pytest $TEST_PATH $PYTEST_FLAGS" | tee -a "$LOG_FILE"

set +e
python -m pytest $TEST_PATH $PYTEST_FLAGS 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
set -e

# ── Result ───────────────────────────────────────────────────────────────────
if [[ $EXIT_CODE -eq 0 ]]; then
  echo "[$(date -u +%FT%TZ)] TEST PASSED" | tee -a "$LOG_FILE"
else
  echo "[$(date -u +%FT%TZ)] TEST FAILED (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"
fi

echo "[INFO] Log: $LOG_FILE"
exit $EXIT_CODE
