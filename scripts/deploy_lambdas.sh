#!/usr/bin/env bash
# =============================================================================
# InsureMail AI — Lambda Deployment Script
# =============================================================================
# Usage:
#   bash scripts/deploy_lambdas.sh --fn <name>      Deploy a single function
#   bash scripts/deploy_lambdas.sh --all             Deploy all Lambda functions
#   bash scripts/deploy_lambdas.sh --step-functions  Update Step Functions definition
#   bash scripts/deploy_lambdas.sh --dashboard       Build + deploy frontend
#   bash scripts/deploy_lambdas.sh --full            All of the above
#   bash scripts/deploy_lambdas.sh --help            Show this message
# =============================================================================

set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────────
BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RED='\033[0;31m'; NC='\033[0m'

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

# ── Lambda name mapping  (short name → deployed function name) ───────────────
# Stored as parallel arrays for bash 3.x compatibility (macOS default shell)
LAMBDA_KEYS=(api_handlers classify_intent claude_response email_parser email_sender rag_ingestion rag_retrieval)
LAMBDA_VALS=(
    "insuremail-ai-dev-api-handlers"
    "insuremail-ai-dev-multi-llm-inference"
    "insuremail-ai-dev-claude-response"
    "insuremail-ai-dev-email-parser"
    "insuremail-ai-dev-email-sender"
    "insuremail-ai-dev-rag-ingestion"
    "insuremail-ai-dev-rag-retrieval"
)

# Lookup function: resolve short name → deployed function name
fn_name_for() {
    local key="$1"
    for i in "${!LAMBDA_KEYS[@]}"; do
        if [[ "${LAMBDA_KEYS[$i]}" == "$key" ]]; then
            echo "${LAMBDA_VALS[$i]}"
            return 0
        fi
    done
    return 1
}

# ── Dashboard config ─────────────────────────────────────────────────────────
DASHBOARD_S3="insuremail-ai-dashboard"
CLOUDFRONT_DIST="E2ADYLCS9LNMWF"
FRONTEND_DIR="$ROOT/dashboard/frontend"

# ── Step Functions config ────────────────────────────────────────────────────
STATE_MACHINE_NAME="insuremail-ai-dev-email-processor"
WORKFLOW_FILE="$ROOT/step-functions/email_processing_workflow.json"

# ─────────────────────────────────────────────────────────────────────────────
log()     { echo -e "${BLUE}[deploy]${NC} $*"; }
success() { echo -e "${GREEN}[deploy]${NC} ✓ $*"; }
warn()    { echo -e "${YELLOW}[deploy]${NC} ⚠ $*"; }
error()   { echo -e "${RED}[deploy]${NC} ✗ $*" >&2; exit 1; }

# ─────────────────────────────────────────────────────────────────────────────
usage() {
    echo -e "${BLUE}InsureMail AI — Lambda Deployment Script${NC}"
    echo
    echo "Usage:"
    echo "  $(basename "$0") --fn <name>       Deploy a single Lambda function"
    echo "  $(basename "$0") --all             Deploy all Lambda functions"
    echo "  $(basename "$0") --step-functions  Update Step Functions definition"
    echo "  $(basename "$0") --dashboard       Build + deploy React frontend"
    echo "  $(basename "$0") --full            All of the above"
    echo "  $(basename "$0") --list            List available function names"
    echo "  $(basename "$0") --help            Show this message"
    echo
    echo "Available function names for --fn:"
    for i in "${!LAMBDA_KEYS[@]}"; do
        printf "  %-20s → %s\n" "${LAMBDA_KEYS[$i]}" "${LAMBDA_VALS[$i]}"
    done
    echo
}

# ─────────────────────────────────────────────────────────────────────────────
check_aws() {
    if ! aws sts get-caller-identity &>/dev/null; then
        error "AWS credentials not configured. Set AWS_PROFILE or AWS_ACCESS_KEY_ID."
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
deploy_lambda() {
    local short_name="$1"
    local fn_name
    fn_name=$(fn_name_for "$short_name") || error "Unknown function '$short_name'. Run --list to see valid names."

    local src_dir="$ROOT/lambda/$short_name"
    if [[ ! -f "$src_dir/lambda_function.py" ]]; then
        error "Source not found: $src_dir/lambda_function.py"
    fi

    local zip_path="/tmp/${short_name}.zip"

    log "Packaging $short_name → $fn_name"

    # Build zip — include lambda_function.py and any sibling .py files
    (cd "$src_dir" && zip -qr "$zip_path" . --exclude "*.pyc" --exclude "__pycache__/*" --exclude "*.dist-info/*")

    log "Uploading code..."
    aws lambda update-function-code \
        --function-name "$fn_name" \
        --zip-file "fileb://$zip_path" \
        --query 'CodeSha256' \
        --output text \
        | xargs -I{} echo "    SHA256: {}"

    log "Waiting for update to complete..."
    aws lambda wait function-updated --function-name "$fn_name"

    success "$short_name deployed"
    rm -f "$zip_path"
}

# ─────────────────────────────────────────────────────────────────────────────
deploy_all_lambdas() {
    log "Deploying all ${#LAMBDA_KEYS[@]} Lambda functions..."
    echo
    local failed=()
    for name in "${LAMBDA_KEYS[@]}"; do
        deploy_lambda "$name" || failed+=("$name")
        echo
    done
    if [[ ${#failed[@]} -gt 0 ]]; then
        error "Failed to deploy: ${failed[*]}"
    fi
    success "All Lambda functions deployed"
}

# ─────────────────────────────────────────────────────────────────────────────
deploy_step_functions() {
    if [[ ! -f "$WORKFLOW_FILE" ]]; then
        error "Workflow file not found: $WORKFLOW_FILE"
    fi

    log "Looking up state machine ARN for '$STATE_MACHINE_NAME'..."
    local arn
    arn=$(aws stepfunctions list-state-machines \
        --query "stateMachines[?name=='${STATE_MACHINE_NAME}'].stateMachineArn" \
        --output text)

    if [[ -z "$arn" ]]; then
        error "State machine '$STATE_MACHINE_NAME' not found."
    fi

    log "Updating state machine: $arn"
    aws stepfunctions update-state-machine \
        --state-machine-arn "$arn" \
        --definition "file://$WORKFLOW_FILE" \
        --query 'updateDate' \
        --output text

    success "Step Functions definition updated"
}

# ─────────────────────────────────────────────────────────────────────────────
deploy_dashboard() {
    if [[ ! -d "$FRONTEND_DIR" ]]; then
        error "Frontend directory not found: $FRONTEND_DIR"
    fi

    # Resolve API URL from Terraform output (or env override)
    local api_url="${VITE_API_BASE_URL:-}"
    if [[ -z "$api_url" ]]; then
        log "Reading API Gateway URL from Terraform..."
        api_url=$(cd "$ROOT/terraform" && terraform output -raw api_gateway_url 2>/dev/null) || true
    fi
    if [[ -z "$api_url" ]]; then
        warn "Could not resolve API Gateway URL. Set VITE_API_BASE_URL to override."
    else
        log "API URL: $api_url"
        echo "VITE_API_BASE_URL=$api_url" > "$FRONTEND_DIR/.env"
    fi

    log "Installing npm dependencies..."
    (cd "$FRONTEND_DIR" && npm install --silent)

    log "Building React frontend..."
    (cd "$FRONTEND_DIR" && npm run build)

    log "Syncing dist/ to s3://$DASHBOARD_S3 ..."
    aws s3 sync "$FRONTEND_DIR/dist/" "s3://$DASHBOARD_S3" --delete

    log "Invalidating CloudFront cache for /index.html ..."
    local inv_id
    inv_id=$(aws cloudfront create-invalidation \
        --distribution-id "$CLOUDFRONT_DIST" \
        --paths "/index.html" \
        --query 'Invalidation.Id' \
        --output text)
    echo "    Invalidation ID: $inv_id"

    success "Dashboard deployed → https://$(aws cloudfront get-distribution \
        --id "$CLOUDFRONT_DIST" \
        --query 'Distribution.DomainName' \
        --output text 2>/dev/null || echo "$DASHBOARD_S3.s3-website.amazonaws.com")"
}

# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────
if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

MODE=""
SINGLE_FN=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fn)
            [[ $# -lt 2 ]] && error "--fn requires a function name argument"
            MODE="single"
            SINGLE_FN="$2"
            shift 2
            ;;
        --all)            MODE="all";           shift ;;
        --step-functions) MODE="step-functions"; shift ;;
        --dashboard)      MODE="dashboard";      shift ;;
        --full)           MODE="full";           shift ;;
        --list)
            echo "Available Lambda short names:"
            for i in "${!LAMBDA_KEYS[@]}"; do
                printf "  %-22s → %s\n" "${LAMBDA_KEYS[$i]}" "${LAMBDA_VALS[$i]}"
            done
            exit 0
            ;;
        --help|-h)        usage; exit 0 ;;
        *) error "Unknown argument: $1. Run --help for usage." ;;
    esac
done

# ─────────────────────────────────────────────────────────────────────────────
echo
echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   InsureMail AI — Deployment${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
echo

check_aws

case "$MODE" in
    single)
        deploy_lambda "$SINGLE_FN"
        ;;
    all)
        deploy_all_lambdas
        ;;
    step-functions)
        deploy_step_functions
        ;;
    dashboard)
        deploy_dashboard
        ;;
    full)
        deploy_all_lambdas
        echo
        deploy_step_functions
        echo
        deploy_dashboard
        ;;
    *)
        usage
        exit 1
        ;;
esac

echo
echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
success "Done."
echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
echo
