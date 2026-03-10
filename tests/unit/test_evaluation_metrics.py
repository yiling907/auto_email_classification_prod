"""
Unit tests for evaluation_metrics Lambda function
"""
import json
import sys
import os
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import patch
import pytest

sys.modules.pop('lambda_function', None)  # avoid module-cache collision when run with other lambda tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/evaluation_metrics'))
import lambda_function


class TestEvaluationMetrics:
    """Test cases for evaluation metrics Lambda"""

    def test_lambda_handler_success(self, lambda_env_vars, dynamodb_tables, lambda_context, sample_model_metrics):
        """Test successful metrics calculation"""
        # Add test data to DynamoDB
        table = dynamodb_tables['metrics']
        table.put_item(Item=sample_model_metrics)

        event = {
            'task_type': 'all',
            'days': 7
        }

        result = lambda_function.lambda_handler(event, lambda_context)

        assert result['statusCode'] == 200
        assert result['task_type'] == 'all'
        assert result['period_days'] == 7
        assert 'statistics' in result
        assert result['sample_count'] == 1

    def test_calculate_statistics_single_model(self, sample_model_metrics):
        """Test statistics calculation for single model"""
        metrics = [sample_model_metrics]

        stats = lambda_function.calculate_statistics(metrics)

        assert stats['total_requests'] == 1
        assert stats['successful_requests'] == 1
        assert stats['success_rate'] == 1.0
        assert stats['avg_latency_ms'] > 0
        assert stats['total_cost_usd'] > 0
        assert 'by_model' in stats
        assert 'mistral-7b' in stats['by_model']

    def test_calculate_statistics_multiple_models(self, sample_model_metrics):
        """Test statistics with multiple models"""
        mistral_metric = sample_model_metrics.copy()
        llama_metric = sample_model_metrics.copy()
        llama_metric['model_name'] = 'llama-3.1-8b'
        llama_metric['model_timestamp'] = 'llama-3.1-8b#2026-03-04T10:30:00.000Z'

        metrics = [mistral_metric, llama_metric]

        stats = lambda_function.calculate_statistics(metrics)

        assert stats['total_requests'] == 2
        assert len(stats['by_model']) == 2
        assert 'mistral-7b' in stats['by_model']
        assert 'llama-3.1-8b' in stats['by_model']

    def test_calculate_statistics_with_failures(self, sample_model_metrics):
        """Test statistics calculation with failed requests"""
        success_metric = sample_model_metrics.copy()
        failed_metric = sample_model_metrics.copy()
        failed_metric['success'] = False
        failed_metric['model_timestamp'] = 'mistral-7b#2026-03-04T10:31:00.000Z'

        metrics = [success_metric, failed_metric]

        stats = lambda_function.calculate_statistics(metrics)

        assert stats['total_requests'] == 2
        assert stats['successful_requests'] == 1
        assert stats['success_rate'] == 0.5

    def test_calculate_statistics_empty_metrics(self):
        """Test statistics calculation with no metrics"""
        stats = lambda_function.calculate_statistics([])

        assert stats['total_requests'] == 0
        assert stats['success_rate'] == 0
        assert stats['avg_latency_ms'] == 0
        assert stats['total_cost_usd'] == 0

    def test_query_metrics_by_task_type(self, lambda_env_vars, dynamodb_tables, sample_model_metrics):
        """Test querying metrics filtered by task type"""
        table = dynamodb_tables['metrics']

        # Add metrics for different task types
        metric1 = sample_model_metrics.copy()
        metric1['task_type'] = 'intent_classification'

        metric2 = sample_model_metrics.copy()
        metric2['task_type'] = 'entity_extraction'
        metric2['model_timestamp'] = 'mistral-7b#2026-03-04T10:31:00.000Z'

        table.put_item(Item=metric1)
        table.put_item(Item=metric2)

        # Query specific task type
        metrics = lambda_function.query_metrics('intent_classification', 7)

        assert len(metrics) == 1
        assert metrics[0]['task_type'] == 'intent_classification'

    def test_query_metrics_time_filter(self, lambda_env_vars, dynamodb_tables, sample_model_metrics):
        """Test querying metrics with time window filter"""
        table = dynamodb_tables['metrics']

        # Add old metric (outside time window)
        old_metric = sample_model_metrics.copy()
        old_date = (datetime.utcnow() - timedelta(days=10)).isoformat() + 'Z'
        old_metric['timestamp'] = old_date
        old_metric['model_timestamp'] = f"mistral-7b#{old_date}"

        # Add recent metric (inside time window)
        recent_metric = sample_model_metrics.copy()

        table.put_item(Item=old_metric)
        table.put_item(Item=recent_metric)

        # Query last 7 days
        metrics = lambda_function.query_metrics('all', 7)

        # Should only return recent metric
        assert len(metrics) == 1
        assert metrics[0]['timestamp'] == recent_metric['timestamp']


class TestModelPerformanceStats:
    """Test model performance statistics calculations"""

    def test_per_model_stats(self, sample_model_metrics):
        """Test per-model statistics calculation"""
        metrics = [sample_model_metrics] * 3  # 3 successful requests

        stats = lambda_function.calculate_statistics(metrics)
        model_stats = stats['by_model']['mistral-7b']

        assert model_stats['total_requests'] == 3
        assert model_stats['successful_requests'] == 3
        assert model_stats['success_rate'] == 1.0
        assert model_stats['avg_latency_ms'] > 0
        assert model_stats['min_latency_ms'] > 0
        assert model_stats['max_latency_ms'] > 0
        assert model_stats['total_cost_usd'] > 0
        assert model_stats['total_input_tokens'] == 450 * 3
        assert model_stats['total_output_tokens'] == 85 * 3

    def test_latency_calculations(self, sample_model_metrics):
        """Test latency min/max/avg calculations"""
        metrics = []
        for i, latency in enumerate([1000, 2000, 3000]):
            metric = sample_model_metrics.copy()
            metric['latency_ms'] = Decimal(str(latency))
            metric['model_timestamp'] = f"mistral-7b#2026-03-04T10:{30+i}:00.000Z"
            metrics.append(metric)

        stats = lambda_function.calculate_statistics(metrics)
        model_stats = stats['by_model']['mistral-7b']

        assert model_stats['min_latency_ms'] == 1000
        assert model_stats['max_latency_ms'] == 3000
        assert model_stats['avg_latency_ms'] == 2000

    def test_cost_calculations(self, sample_model_metrics):
        """Test cost aggregation"""
        metrics = []
        for i in range(5):
            metric = sample_model_metrics.copy()
            metric['cost_usd'] = Decimal('0.0001')
            metric['model_timestamp'] = f"mistral-7b#2026-03-04T10:{30+i}:00.000Z"
            metrics.append(metric)

        stats = lambda_function.calculate_statistics(metrics)
        model_stats = stats['by_model']['mistral-7b']

        assert model_stats['total_cost_usd'] == 0.0005
        assert model_stats['avg_cost_usd'] == 0.0001
