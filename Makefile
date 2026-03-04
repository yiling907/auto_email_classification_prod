# Makefile for InsureMail AI Project
# Provides convenient commands for testing, deployment, and maintenance

.PHONY: help test test-unit test-integration test-terraform lint fmt clean deploy install

# Default target
.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)═══════════════════════════════════════════════$(NC)"
	@echo "$(BLUE)   InsureMail AI - Available Commands$(NC)"
	@echo "$(BLUE)═══════════════════════════════════════════════$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

install: ## Install all dependencies (Python and Node.js)
	@echo "$(BLUE)Installing Python dependencies...$(NC)"
	pip install -r tests/requirements.txt
	@echo "$(GREEN)✓ Dependencies installed$(NC)"

test: ## Run all tests (unit + integration + terraform)
	@echo "$(BLUE)Running all tests...$(NC)"
	@bash scripts/run_tests.sh all

test-unit: ## Run unit tests only
	@echo "$(BLUE)Running unit tests...$(NC)"
	@bash scripts/run_tests.sh unit

test-integration: ## Run integration tests only
	@echo "$(BLUE)Running integration tests...$(NC)"
	@bash scripts/run_tests.sh integration

test-terraform: ## Run Terraform validation tests
	@echo "$(BLUE)Running Terraform tests...$(NC)"
	@bash scripts/run_tests.sh terraform

test-coverage: ## Run tests with coverage report
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	pytest tests/ --cov=lambda --cov-report=html --cov-report=term-missing
	@echo "$(GREEN)Coverage report: file://$(PWD)/htmlcov/index.html$(NC)"

test-fast: ## Run fast tests only (exclude slow tests)
	@echo "$(BLUE)Running fast tests...$(NC)"
	pytest tests/ -m "not slow" -v

lint: ## Run code linting (flake8, black check)
	@echo "$(BLUE)Running linters...$(NC)"
	@bash scripts/run_tests.sh lint

fmt: ## Format code with black
	@echo "$(BLUE)Formatting Python code...$(NC)"
	black lambda/ tests/ --line-length 120
	@echo "$(GREEN)✓ Code formatted$(NC)"

fmt-check: ## Check code formatting without making changes
	@echo "$(BLUE)Checking code formatting...$(NC)"
	black lambda/ tests/ --check --line-length 120

clean: ## Clean up test artifacts and cache
	@echo "$(BLUE)Cleaning up...$(NC)"
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf **/__pycache__
	rm -rf **/*.pyc
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

# Terraform commands
tf-init: ## Initialize Terraform
	@echo "$(BLUE)Initializing Terraform...$(NC)"
	cd terraform && terraform init

tf-validate: ## Validate Terraform configuration
	@echo "$(BLUE)Validating Terraform...$(NC)"
	cd terraform && terraform init -backend=false && terraform validate

tf-fmt: ## Format Terraform files
	@echo "$(BLUE)Formatting Terraform files...$(NC)"
	cd terraform && terraform fmt -recursive

tf-plan: ## Run Terraform plan
	@echo "$(BLUE)Running Terraform plan...$(NC)"
	cd terraform && terraform plan

tf-apply: ## Apply Terraform changes
	@echo "$(YELLOW)⚠ This will deploy to AWS$(NC)"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		cd terraform && terraform apply; \
	fi

# Lambda deployment
deploy-lambda: ## Deploy all Lambda functions
	@echo "$(BLUE)Deploying Lambda functions...$(NC)"
	cd terraform && terraform apply -target=module.lambda -auto-approve
	@echo "$(GREEN)✓ Lambda functions deployed$(NC)"

deploy-all: ## Deploy entire infrastructure
	@echo "$(YELLOW)⚠ This will deploy all infrastructure to AWS$(NC)"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		cd terraform && terraform apply; \
	fi

# Dashboard commands
dashboard-build: ## Build React dashboard
	@echo "$(BLUE)Building dashboard...$(NC)"
	cd dashboard/frontend && npm run build
	@echo "$(GREEN)✓ Dashboard built$(NC)"

dashboard-deploy: ## Deploy dashboard to S3
	@echo "$(BLUE)Deploying dashboard...$(NC)"
	cd dashboard/frontend && npm run deploy
	@echo "$(GREEN)✓ Dashboard deployed$(NC)"

# Development commands
dev-setup: install tf-init ## Setup development environment
	@echo "$(GREEN)✓ Development environment ready$(NC)"

check: lint test-fast ## Quick check before commit (lint + fast tests)

pre-commit: fmt lint test ## Full pre-commit check (format + lint + test)

# CI/CD simulation
ci: clean install lint test tf-validate ## Simulate CI pipeline
	@echo "$(GREEN)✓ CI checks passed$(NC)"

# Documentation
docs: ## Generate test documentation
	@echo "$(BLUE)Generating test documentation...$(NC)"
	pytest tests/ --collect-only --quiet
	@echo "$(GREEN)✓ Documentation generated$(NC)"

# Status and info
status: ## Show project status
	@echo "$(BLUE)═══════════════════════════════════════════════$(NC)"
	@echo "$(BLUE)   InsureMail AI - Project Status$(NC)"
	@echo "$(BLUE)═══════════════════════════════════════════════$(NC)"
	@echo ""
	@echo "$(GREEN)Python Version:$(NC)"
	@python --version
	@echo ""
	@echo "$(GREEN)Terraform Status:$(NC)"
	@cd terraform && terraform workspace show 2>/dev/null || echo "Not initialized"
	@echo ""
	@echo "$(GREEN)Test Count:$(NC)"
	@find tests/ -name "test_*.py" -type f | wc -l | xargs echo "  Test files:"
	@echo ""
	@echo "$(GREEN)Lambda Functions:$(NC)"
	@ls -1 lambda/ | grep -v __pycache__ | wc -l | xargs echo "  Functions:"
