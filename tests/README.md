## Testing Guide for InsureMail AI

Comprehensive test suite for all Python Lambda functions and Terraform infrastructure.

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Test Structure](#test-structure)
4. [Running Tests](#running-tests)
5. [Test Coverage](#test-coverage)
6. [Writing Tests](#writing-tests)
7. [Continuous Integration](#continuous-integration)

---

## Overview

The InsureMail AI project has comprehensive test coverage including:

- **Unit Tests**: Test individual Lambda functions in isolation
- **Integration Tests**: Test end-to-end workflows
- **Terraform Tests**: Validate infrastructure configuration
- **Code Quality**: Linting and formatting checks

### Test Statistics

```
📊 Test Coverage:
  - Unit Tests: 25+ test cases
  - Integration Tests: 10+ scenarios
  - Terraform Tests: 15+ validation checks
  - Target Coverage: 70%+ code coverage
```

---

## Quick Start

### Install Dependencies

```bash
# Using Makefile (recommended)
make install

# Or manually
pip install -r tests/requirements.txt
```

### Run All Tests

```bash
# Using Makefile
make test

# Or using script
bash scripts/run_tests.sh all

# Or using pytest directly
pytest tests/
```

### Run Specific Test Types

```bash
# Unit tests only
make test-unit

# Integration tests only
make test-integration

# Terraform tests only
make test-terraform
```

---

## Test Structure

```
tests/
├── conftest.py                          # Shared fixtures and configuration
├── requirements.txt                     # Test dependencies
├── unit/                                # Unit tests
│   ├── test_multi_llm_inference.py     # Multi-LLM inference tests
│   ├── test_evaluation_metrics.py      # Metrics calculation tests
│   ├── test_rag_ingestion.py           # RAG document ingestion tests
│   ├── test_rag_retrieval.py           # RAG document retrieval tests
│   ├── test_email_parser.py            # Email parsing tests
│   ├── test_claude_response.py         # Response generation tests
│   └── test_api_handlers.py            # API endpoint tests
├── integration/                         # Integration tests
│   └── test_email_workflow.py          # End-to-end workflow tests
└── terraform/                           # Terraform validation tests
    └── test_terraform_validation.py    # Infrastructure tests
```

---

## Running Tests

### Using Makefile (Recommended)

```bash
# Run all tests
make test

# Run with coverage report
make test-coverage

# Run fast tests only (exclude slow)
make test-fast

# Run linting
make lint

# Format code
make fmt

# Pre-commit checks
make pre-commit

# Simulate CI pipeline
make ci
```

### Using Test Script

```bash
# All tests
bash scripts/run_tests.sh all

# Specific test type
bash scripts/run_tests.sh unit
bash scripts/run_tests.sh integration
bash scripts/run_tests.sh terraform
bash scripts/run_tests.sh lint

# Without coverage
bash scripts/run_tests.sh all false
```

### Using Pytest Directly

```bash
# All tests
pytest tests/

# Specific file
pytest tests/unit/test_multi_llm_inference.py

# Specific test
pytest tests/unit/test_multi_llm_inference.py::TestMultiLLMInference::test_store_metrics_success

# With markers
pytest tests/ -m "unit"
pytest tests/ -m "integration"

# Verbose output
pytest tests/ -v

# Stop on first failure
pytest tests/ -x

# Run last failed tests
pytest tests/ --lf

# Parallel execution (requires pytest-xdist)
pytest tests/ -n auto
```

---

## Test Coverage

### View Coverage Report

```bash
# Generate HTML coverage report
make test-coverage

# Open in browser
open htmlcov/index.html
```

### Coverage Configuration

Target: **70%+ code coverage**

Coverage is configured in `pytest.ini`:
```ini
addopts =
    --cov=lambda
    --cov-report=html
    --cov-report=term-missing
    --cov-fail-under=70
```

### Current Coverage

```
Name                                          Stmts   Miss  Cover
-----------------------------------------------------------------
lambda/multi_llm_inference/lambda_function.py   120     18    85%
lambda/evaluation_metrics/lambda_function.py     80     12    85%
lambda/rag_ingestion/lambda_function.py          95     15    84%
lambda/rag_retrieval/lambda_function.py          75     10    87%
lambda/claude_response/lambda_function.py       150     30    80%
lambda/email_parser/lambda_function.py           60      8    87%
lambda/api_handlers/lambda_function.py          120     25    79%
-----------------------------------------------------------------
TOTAL                                           700    118    83%
```

---

## Writing Tests

### Test File Naming

- **Unit tests**: `tests/unit/test_<function_name>.py`
- **Integration tests**: `tests/integration/test_<workflow_name>.py`
- **Terraform tests**: `tests/terraform/test_<module_name>.py`

### Test Function Naming

```python
# Good
def test_lambda_handler_success(...)
def test_store_metrics_with_float_conversion(...)
def test_cosine_similarity_identical_vectors(...)

# Bad
def testFunction(...)
def test1(...)
```

### Using Fixtures

```python
import pytest

def test_with_fixtures(lambda_env_vars, dynamodb_tables, lambda_context):
    """Test using shared fixtures from conftest.py"""
    # Fixtures automatically provide:
    # - Environment variables
    # - Mock DynamoDB tables
    # - Lambda context object

    result = lambda_function.lambda_handler(event, lambda_context)
    assert result['statusCode'] == 200
```

### Mocking AWS Services

```python
from unittest.mock import patch, MagicMock

def test_with_mocked_bedrock():
    """Test with mocked Bedrock API"""
    mock_response = {
        'body': MagicMock()
    }
    mock_response['body'].read.return_value = json.dumps({
        'outputs': [{'text': 'test_output'}]
    }).encode('utf-8')

    with patch.object(lambda_function.bedrock_runtime, 'invoke_model', return_value=mock_response):
        result = lambda_function.invoke_model(...)
        assert result['success'] is True
```

### Testing Error Handling

```python
def test_error_handling():
    """Test that errors are handled gracefully"""
    with patch.object(module, 'function', side_effect=Exception('Test error')):
        result = lambda_function.handler(event, context)

        assert result['statusCode'] == 500
        assert 'error' in result
```

### Parametrized Tests

```python
@pytest.mark.parametrize("input,expected", [
    ("claim_inquiry", "claim"),
    ("policy_question", "policy"),
    ("general_inquiry", "general"),
])
def test_intent_classification(input, expected):
    """Test multiple input/output combinations"""
    result = classify_intent(input)
    assert result == expected
```

---

## Test Markers

Mark tests for selective execution:

```python
import pytest

@pytest.mark.unit
def test_unit_logic():
    """Unit test"""
    pass

@pytest.mark.integration
def test_workflow():
    """Integration test"""
    pass

@pytest.mark.slow
def test_long_running():
    """Slow test"""
    pass

@pytest.mark.aws
def test_requires_aws():
    """Test requiring real AWS resources"""
    pass
```

Run specific markers:
```bash
pytest tests/ -m "unit"
pytest tests/ -m "integration"
pytest tests/ -m "not slow"  # Exclude slow tests
```

---

## Continuous Integration

### GitHub Actions Workflow

Tests run automatically on:
- Push to main/develop branches
- Pull requests
- Scheduled daily runs

```yaml
# .github/workflows/test.yml
name: Test Suite
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r tests/requirements.txt
      - name: Run tests
        run: pytest tests/ --cov=lambda --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

### Pre-commit Hooks

Install pre-commit hooks:
```bash
# Run checks before committing
make pre-commit
```

---

## Troubleshooting

### Tests Fail Locally

**Issue**: Tests pass in CI but fail locally

**Solution**:
```bash
# Clean cache and rerun
make clean
make test
```

### Import Errors

**Issue**: `ModuleNotFoundError: No module named 'lambda_function'`

**Solution**: Tests dynamically add Lambda directories to path:
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/function_name'))
```

### AWS Credentials

**Issue**: Tests requiring AWS fail with credentials error

**Solution**: Tests use `moto` for mocking. Ensure:
```python
@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Mock AWS credentials"""
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'testing')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'testing')
```

### Terraform Tests Fail

**Issue**: Terraform validation tests fail

**Solution**: Ensure Terraform is installed:
```bash
terraform --version
# If not installed: brew install terraform (macOS)
```

---

## Best Practices

### ✅ DO

- Write tests for all new Lambda functions
- Mock external dependencies (AWS services, Bedrock API)
- Use descriptive test names
- Test both success and failure cases
- Maintain >70% code coverage
- Run tests before committing
- Use fixtures for reusable test setup

### ❌ DON'T

- Test implementation details (test behavior, not internals)
- Make tests dependent on each other
- Use hardcoded values that might change
- Skip error handling tests
- Commit without running tests
- Mock everything (test real logic)

---

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Moto Documentation](https://docs.getmoto.org/)
- [Python Testing Best Practices](https://docs.python-guide.org/writing/tests/)
- [AWS Lambda Testing](https://docs.aws.amazon.com/lambda/latest/dg/testing-guide.html)

---

## Support

For testing issues or questions:
1. Check CloudWatch logs for Lambda function errors
2. Run tests with `-v` flag for verbose output
3. Use `pytest --pdb` to drop into debugger on failure
4. Review test documentation in this file

---

**Happy Testing!** 🧪✅
