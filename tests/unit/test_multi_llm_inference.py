"""
Unit tests for multi_llm_inference Lambda function
"""
import json
import sys
import os
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/multi_llm_inference'))
import lambda_function


class TestMultiLLMInference:
    """Test cases for multi-LLM inference Lambda"""

    def test_lambda_handler_success(self, lambda_env_vars, dynamodb_tables, lambda_context):
        """Test successful lambda handler execution"""
        event = {
            'prompt': 'Classify the intent of this email: I need help with my claim',
            'task_type': 'intent_classification'
        }

        with patch.object(lambda_function, 'run_parallel_inference') as mock_inference:
            mock_inference.return_value = [
                {
                    'model_name': 'mistral-7b',
                    'output_text': 'claim_inquiry',
                    'success': True
                }
            ]

            result = lambda_function.lambda_handler(event, lambda_context)

            assert result['statusCode'] == 200
            assert result['task_type'] == 'intent_classification'
            assert len(result['results']) == 1
            assert result['results'][0]['model_name'] == 'mistral-7b'

    def test_lambda_handler_missing_prompt(self, lambda_env_vars, lambda_context):
        """Test handler with missing prompt"""
        event = {'task_type': 'intent_classification'}

        result = lambda_function.lambda_handler(event, lambda_context)

        assert result['statusCode'] == 500
        assert 'error' in result
        assert 'Missing prompt' in result['error']

    def test_store_metrics_success(self, lambda_env_vars, dynamodb_tables):
        """Test metrics storage to DynamoDB"""
        result = {
            'model_id': 'mistral.mistral-7b-instruct-v0:2',
            'input_tokens': 450,
            'output_tokens': 85,
            'latency_ms': 1850.5,
            'cost_usd': 0.000085,
            'success': True
        }

        # Should not raise exception
        lambda_function.store_metrics('intent_classification', 'mistral-7b', result)

        # Verify data was stored
        table = dynamodb_tables['metrics']
        response = table.scan()
        assert response['Count'] == 1

        item = response['Items'][0]
        assert item['task_type'] == 'intent_classification'
        assert item['model_name'] == 'mistral-7b'
        assert item['input_tokens'] == 450
        assert item['output_tokens'] == 85
        assert isinstance(item['latency_ms'], Decimal)
        assert isinstance(item['cost_usd'], Decimal)

    def test_store_metrics_float_conversion(self, lambda_env_vars, dynamodb_tables):
        """Test that float values are properly converted to Decimal"""
        result = {
            'model_id': 'test-model',
            'input_tokens': 100.5,  # Float input
            'output_tokens': 50.7,  # Float input
            'latency_ms': 1234.567,
            'cost_usd': 0.000123,
            'success': True
        }

        lambda_function.store_metrics('test_task', 'test-model', result)

        table = dynamodb_tables['metrics']
        response = table.scan()
        item = response['Items'][0]

        # Verify types are correct for DynamoDB
        assert isinstance(item['input_tokens'], int)
        assert isinstance(item['output_tokens'], int)
        assert isinstance(item['latency_ms'], Decimal)
        assert isinstance(item['cost_usd'], Decimal)

    def test_calculate_cost(self):
        """Test cost calculation"""
        model_config = {
            'cost_per_1k_input': 0.00015,
            'cost_per_1k_output': 0.00020
        }

        cost = lambda_function.calculate_cost(450, 85, model_config)

        expected = (450 / 1000) * 0.00015 + (85 / 1000) * 0.00020
        assert abs(cost - expected) < 0.000001

    def test_invoke_model_mistral_format(self, lambda_env_vars):
        """Test Mistral model invocation and response parsing"""
        model_config = {
            'id': 'mistral.mistral-7b-instruct-v0:2',
            'type': 'mistral',
            'cost_per_1k_input': 0.00015,
            'cost_per_1k_output': 0.00020
        }

        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = json.dumps({
            'outputs': [{'text': 'claim_inquiry'}]
        }).encode('utf-8')

        with patch.object(lambda_function.bedrock_runtime, 'invoke_model', return_value=mock_response):
            with patch.object(lambda_function, 'store_metrics'):
                result = lambda_function.invoke_model(
                    'mistral-7b',
                    model_config,
                    'Test prompt',
                    'intent_classification'
                )

                assert result['success'] is True
                assert result['model_name'] == 'mistral-7b'
                assert result['output_text'] == 'claim_inquiry'
                assert result['input_tokens'] > 0
                assert result['output_tokens'] > 0

    def test_invoke_model_error_handling(self, lambda_env_vars):
        """Test error handling when model invocation fails"""
        model_config = {
            'id': 'test-model',
            'type': 'mistral',
            'cost_per_1k_input': 0.00015,
            'cost_per_1k_output': 0.00020
        }

        with patch.object(lambda_function.bedrock_runtime, 'invoke_model', side_effect=Exception('Model error')):
            result = lambda_function.invoke_model(
                'test-model',
                model_config,
                'Test prompt',
                'test_task'
            )

            assert result['success'] is False
            assert 'error' in result
            assert 'Model error' in result['error']
            assert 'latency_ms' in result


class TestParallelInference:
    """Test parallel model inference"""

    def test_run_parallel_inference(self, lambda_env_vars):
        """Test parallel inference across multiple models"""
        with patch.object(lambda_function, 'invoke_model') as mock_invoke:
            mock_invoke.side_effect = [
                {'model_name': 'mistral-7b', 'success': True},
                {'model_name': 'llama-3.1-8b', 'success': True}
            ]

            results = lambda_function.run_parallel_inference('Test prompt', 'test_task')

            assert len(results) == 2
            assert all(r['success'] for r in results)

    def test_run_parallel_inference_partial_failure(self, lambda_env_vars):
        """Test parallel inference with some models failing"""
        with patch.object(lambda_function, 'invoke_model') as mock_invoke:
            mock_invoke.side_effect = [
                {'model_name': 'mistral-7b', 'success': True},
                Exception('Model unavailable')
            ]

            results = lambda_function.run_parallel_inference('Test prompt', 'test_task')

            # Should return results for both (one success, one failure)
            assert len(results) == 2
            assert results[0]['success'] is True
            assert results[1]['success'] is False
