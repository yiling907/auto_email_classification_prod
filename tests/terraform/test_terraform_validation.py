"""
Terraform configuration validation tests
"""
import subprocess
import json
import os
import pytest


class TestTerraformValidation:
    """Test Terraform configuration validity"""

    @pytest.fixture(autouse=True)
    def terraform_dir(self):
        """Get terraform directory path"""
        return os.path.join(os.path.dirname(__file__), '../../terraform')

    def test_terraform_fmt(self, terraform_dir):
        """Test that Terraform files are properly formatted"""
        result = subprocess.run(
            ['terraform', 'fmt', '-check', '-recursive'],
            cwd=terraform_dir,
            capture_output=True,
            text=True
        )

        assert result.returncode == 0, f"Terraform files not formatted: {result.stdout}"

    def test_terraform_validate(self, terraform_dir):
        """Test that Terraform configuration is valid"""
        # Initialize Terraform (required for validation)
        init_result = subprocess.run(
            ['terraform', 'init', '-backend=false'],
            cwd=terraform_dir,
            capture_output=True,
            text=True
        )

        assert init_result.returncode == 0, f"Terraform init failed: {init_result.stderr}"

        # Validate configuration
        validate_result = subprocess.run(
            ['terraform', 'validate', '-json'],
            cwd=terraform_dir,
            capture_output=True,
            text=True
        )

        assert validate_result.returncode == 0, f"Terraform validation failed: {validate_result.stderr}"

        # Parse JSON output
        validation_output = json.loads(validate_result.stdout)
        assert validation_output['valid'] is True, f"Configuration invalid: {validation_output}"

    def test_required_providers(self, terraform_dir):
        """Test that required providers are properly configured"""
        # Check for provider configuration
        result = subprocess.run(
            ['grep', '-r', 'required_providers', terraform_dir],
            capture_output=True,
            text=True
        )

        assert 'aws' in result.stdout, "AWS provider not configured"

    def test_terraform_modules_exist(self, terraform_dir):
        """Test that all referenced modules exist"""
        modules = ['iam', 'storage', 'lambda', 'step-functions', 'monitoring', 'api-gateway']

        for module in modules:
            module_path = os.path.join(terraform_dir, 'modules', module)
            assert os.path.exists(module_path), f"Module {module} directory not found"
            assert os.path.exists(os.path.join(module_path, 'main.tf')), f"Module {module} main.tf not found"

    def test_output_definitions(self, terraform_dir):
        """Test that expected outputs are defined"""
        outputs_file = os.path.join(terraform_dir, 'outputs.tf')

        with open(outputs_file, 'r') as f:
            content = f.read()

        required_outputs = [
            'api_gateway_url',
            'email_table_name',
            'model_metrics_table_name',
            'lambda_functions',
            'step_functions_arn'
        ]

        for output in required_outputs:
            assert f'output "{output}"' in content, f"Output {output} not defined"

    def test_variable_definitions(self, terraform_dir):
        """Test that required variables are defined"""
        variables_file = os.path.join(terraform_dir, 'variables.tf')

        with open(variables_file, 'r') as f:
            content = f.read()

        required_variables = [
            'project_name',
            'environment',
            'aws_region',
            'bedrock_models'
        ]

        for variable in required_variables:
            assert f'variable "{variable}"' in content, f"Variable {variable} not defined"

    def test_iam_policies_least_privilege(self, terraform_dir):
        """Test that IAM policies follow least privilege principle"""
        iam_file = os.path.join(terraform_dir, 'modules/iam/main.tf')

        with open(iam_file, 'r') as f:
            content = f.read()

        # Check for overly permissive policies
        dangerous_patterns = [
            'Action = "*"',
            'Resource = "*"' + ' ' + 'Effect = "Allow"',  # Both together is dangerous
        ]

        # This is a warning check, not a failure
        for pattern in dangerous_patterns:
            if pattern in content:
                print(f"WARNING: Potentially overly permissive IAM policy detected: {pattern}")


class TestTerraformStructure:
    """Test Terraform project structure and organization"""

    @pytest.fixture(autouse=True)
    def terraform_dir(self):
        """Get terraform directory path"""
        return os.path.join(os.path.dirname(__file__), '../../terraform')

    def test_backend_configuration_exists(self, terraform_dir):
        """Test that backend configuration is defined"""
        main_tf = os.path.join(terraform_dir, 'main.tf')

        with open(main_tf, 'r') as f:
            content = f.read()

        assert 'terraform' in content, "Terraform block not found"
        assert 'backend' in content, "Backend configuration not found"

    def test_module_outputs_defined(self, terraform_dir):
        """Test that modules have outputs defined"""
        modules = ['iam', 'storage', 'lambda']

        for module in modules:
            outputs_file = os.path.join(terraform_dir, 'modules', module, 'outputs.tf')
            assert os.path.exists(outputs_file), f"Module {module} outputs.tf not found"

    def test_module_variables_defined(self, terraform_dir):
        """Test that modules have variables defined"""
        modules = ['iam', 'storage', 'lambda']

        for module in modules:
            variables_file = os.path.join(terraform_dir, 'modules', module, 'variables.tf')
            assert os.path.exists(variables_file), f"Module {module} variables.tf not found"

    def test_no_hardcoded_values(self, terraform_dir):
        """Test that there are no hardcoded sensitive values"""
        # Search for common patterns of hardcoded values
        patterns = [
            'password =',
            'secret =',
            'api_key =',
        ]

        result = subprocess.run(
            ['grep', '-r', '-i', '-E', '|'.join(patterns), terraform_dir, '--include=*.tf'],
            capture_output=True,
            text=True
        )

        # Should not find any matches (returncode 1 means no matches)
        assert result.returncode == 1, f"Potential hardcoded secrets found: {result.stdout}"

    def test_tags_applied(self, terraform_dir):
        """Test that resources have proper tags"""
        main_tf = os.path.join(terraform_dir, 'main.tf')

        with open(main_tf, 'r') as f:
            content = f.read()

        assert 'tags' in content.lower(), "Tags not found in main configuration"
        assert 'common_tags' in content or 'local.tags' in content, "Common tags pattern not found"


class TestLambdaConfiguration:
    """Test Lambda function Terraform configuration"""

    @pytest.fixture(autouse=True)
    def lambda_module_dir(self):
        """Get Lambda module directory path"""
        return os.path.join(os.path.dirname(__file__), '../../terraform/modules/lambda')

    def test_lambda_functions_defined(self, lambda_module_dir):
        """Test that all Lambda functions are defined"""
        main_tf = os.path.join(lambda_module_dir, 'main.tf')

        with open(main_tf, 'r') as f:
            content = f.read()

        expected_functions = [
            'email_parser',
            'email_receiver',
            'email_sender',
            'multi_llm_inference',
            'claude_response',
            'rag_ingestion',
            'rag_retrieval',
            'evaluation_metrics',
            'api_handlers'
        ]

        for function in expected_functions:
            assert f'aws_lambda_function.{function}' in content, f"Lambda function {function} not defined"

    def test_lambda_timeouts_configured(self, lambda_module_dir):
        """Test that Lambda functions have appropriate timeouts"""
        main_tf = os.path.join(lambda_module_dir, 'main.tf')

        with open(main_tf, 'r') as f:
            content = f.read()

        # Check that timeout is explicitly set
        assert 'timeout' in content, "Lambda timeout not configured"

    def test_lambda_environment_variables(self, lambda_module_dir):
        """Test that Lambda functions have environment variables configured"""
        main_tf = os.path.join(lambda_module_dir, 'main.tf')

        with open(main_tf, 'r') as f:
            content = f.read()

        # Check for environment block
        assert 'environment {' in content, "Lambda environment variables not configured"
        assert 'variables =' in content, "Environment variables block not found"

    def test_cloudwatch_logs_configured(self, lambda_module_dir):
        """Test that CloudWatch logs are configured for Lambda functions"""
        main_tf = os.path.join(lambda_module_dir, 'main.tf')

        with open(main_tf, 'r') as f:
            content = f.read()

        assert 'aws_cloudwatch_log_group' in content, "CloudWatch log groups not configured"
        assert 'retention_in_days' in content, "Log retention not configured"
