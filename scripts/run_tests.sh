#!/bin/bash

# Test Runner Script for InsureMail AI
# Runs comprehensive tests for Python Lambda functions and Terraform configuration

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   InsureMail AI - Test Suite Runner${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

# Check if virtual environment exists
if [ ! -d "$PROJECT_ROOT/venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    python3 -m venv "$PROJECT_ROOT/venv"
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source "$PROJECT_ROOT/venv/bin/activate"

# Install test dependencies
echo -e "${BLUE}Installing test dependencies...${NC}"
pip install -q -r "$PROJECT_ROOT/tests/requirements.txt"

cd "$PROJECT_ROOT"

# Parse command line arguments
TEST_TYPE="${1:-all}"
COVERAGE="${2:-true}"

echo
echo -e "${GREEN}Test Configuration:${NC}"
echo "  Test Type: $TEST_TYPE"
echo "  Coverage: $COVERAGE"
echo

# Function to run unit tests
run_unit_tests() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  Running Unit Tests${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo

    if [ "$COVERAGE" = "true" ]; then
        pytest tests/unit/ \
            --cov=lambda \
            --cov-report=html \
            --cov-report=term-missing \
            -v
    else
        pytest tests/unit/ -v
    fi

    echo
    echo -e "${GREEN}✓ Unit tests completed${NC}"
}

# Function to run integration tests
run_integration_tests() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  Running Integration Tests${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo

    pytest tests/integration/ -v

    echo
    echo -e "${GREEN}✓ Integration tests completed${NC}"
}

# Function to run Terraform tests
run_terraform_tests() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  Running Terraform Tests${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo

    # Check if Terraform is installed
    if ! command -v terraform &> /dev/null; then
        echo -e "${RED}✗ Terraform not installed. Skipping Terraform tests.${NC}"
        return
    fi

    pytest tests/terraform/ -v

    echo
    echo -e "${GREEN}✓ Terraform tests completed${NC}"
}

# Function to run linting
run_linting() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  Running Code Linting${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo

    echo "Checking Python code with flake8..."
    flake8 lambda/ tests/ --max-line-length=120 --exclude=venv,node_modules || true

    echo
    echo -e "${GREEN}✓ Linting completed${NC}"
}

# Function to generate coverage report
generate_coverage_report() {
    if [ "$COVERAGE" = "true" ] && [ -f ".coverage" ]; then
        echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${BLUE}  Coverage Report${NC}"
        echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo

        coverage report

        echo
        echo -e "${GREEN}HTML coverage report: file://$(pwd)/htmlcov/index.html${NC}"
    fi
}

# Main test execution
case "$TEST_TYPE" in
    unit)
        run_unit_tests
        ;;
    integration)
        run_integration_tests
        ;;
    terraform)
        run_terraform_tests
        ;;
    lint)
        run_linting
        ;;
    all)
        run_unit_tests
        echo
        run_integration_tests
        echo
        run_terraform_tests
        echo
        run_linting
        ;;
    *)
        echo -e "${RED}Unknown test type: $TEST_TYPE${NC}"
        echo "Usage: $0 [unit|integration|terraform|lint|all] [true|false]"
        exit 1
        ;;
esac

echo
generate_coverage_report

echo
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ All tests completed successfully!${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo

# Return exit code
exit 0
