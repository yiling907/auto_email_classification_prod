"""
Integration tests for end-to-end email processing workflow
"""
import json
import sys
import os
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/email_parser'))
import lambda_function as email_parser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/multi_llm_inference'))
import lambda_function as multi_llm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/rag_retrieval'))
import lambda_function as rag_retrieval

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/claude_response'))
import lambda_function as claude_response


class TestEmailProcessingWorkflow:
    """Integration tests for complete email processing workflow"""

    def test_end_to_end_email_processing(
        self,
        lambda_env_vars,
        s3_buckets,
        dynamodb_tables,
        lambda_context,
        sample_email,
        sample_rag_document
    ):
        """Test complete email processing flow from parse to response"""

        # Step 1: Email Parser
        # Upload raw email to S3
        raw_email = f"""From: {sample_email['from_address']}
To: {sample_email['to_address']}
Subject: {sample_email['subject']}
Date: {sample_email['timestamp']}

{sample_email['body']}
"""
        s3_buckets.put_object(
            Bucket='test-emails-bucket',
            Key='emails/test_email.txt',
            Body=raw_email.encode('utf-8')
        )

        parser_event = {
            'bucket': 'test-emails-bucket',
            'key': 'emails/test_email.txt'
        }

        parsed_result = email_parser.lambda_handler(parser_event, lambda_context)
        assert parsed_result['statusCode'] == 200
        assert 'email_id' in parsed_result
        assert parsed_result['parsed_data']['subject'] == sample_email['subject']

        # Step 2: Multi-LLM Inference (Intent Classification)
        intent_event = {
            'prompt': f"Classify intent: {sample_email['body']}",
            'task_type': 'intent_classification'
        }

        mock_bedrock_response = {
            'body': MagicMock()
        }
        mock_bedrock_response['body'].read.return_value = json.dumps({
            'outputs': [{'text': 'claim_inquiry'}]
        }).encode('utf-8')

        with patch.object(multi_llm.bedrock_runtime, 'invoke_model', return_value=mock_bedrock_response):
            intent_result = multi_llm.lambda_handler(intent_event, lambda_context)

            assert intent_result['statusCode'] == 200
            assert len(intent_result['results']) > 0

        # Step 3: RAG Retrieval
        # Add RAG document to database
        table = dynamodb_tables['embeddings']
        doc = sample_rag_document.copy()
        doc['embedding'] = json.dumps(doc['embedding'])
        table.put_item(Item=doc)

        rag_event = {
            'email_text': sample_email['body'],
            'top_k': 3
        }

        mock_embedding = [0.1] * 1536
        with patch.object(rag_retrieval, 'generate_embedding', return_value=mock_embedding):
            rag_result = rag_retrieval.lambda_handler(rag_event, lambda_context)

            assert rag_result['statusCode'] == 200
            assert 'retrieved_documents' in rag_result

        # Step 4: Response Generation
        response_event = {
            'email_id': parsed_result['email_id'],
            'email_body': sample_email['body'],
            'subject': sample_email['subject'],
            'entities': {},
            'intent': {'results': [{'output_text': 'claim_inquiry', 'success': True}]},
            'rag_documents': rag_result['retrieved_documents'],
            'crm_validation': {'policy_exists': True},
            'fraud_score': {'risk_level': 'low'}
        }

        mock_claude_response = {
            'body': MagicMock()
        }
        mock_claude_response['body'].read.return_value = json.dumps({
            'outputs': [{
                'text': json.dumps({
                    'response_text': 'Thank you for your inquiry about your claim.',
                    'confidence_score': 0.85,
                    'reference_ids': ['policy_001'],
                    'compliance_checks': {
                        'contains_disclaimer': True,
                        'factually_accurate': True,
                        'references_policy': True
                    },
                    'reasoning': 'Based on policy documents'
                })
            }]
        }).encode('utf-8')

        with patch.object(claude_response.bedrock_runtime, 'invoke_model', return_value=mock_claude_response):
            final_result = claude_response.lambda_handler(response_event, lambda_context)

            assert final_result['statusCode'] == 200
            assert final_result['confidence_score'] >= 0.8
            assert final_result['action'] == 'auto_response'
            assert 'response_text' in final_result

    def test_workflow_with_low_confidence(
        self,
        lambda_env_vars,
        dynamodb_tables,
        lambda_context,
        sample_email
    ):
        """Test workflow when confidence is low (should escalate)"""

        response_event = {
            'email_body': sample_email['body'],
            'subject': sample_email['subject'],
            'entities': {},
            'intent': {'results': [{'output_text': 'unknown', 'success': True}]},
            'rag_documents': [],
            'crm_validation': {},
            'fraud_score': {'risk_level': 'high'}
        }

        mock_claude_response = {
            'body': MagicMock()
        }
        mock_claude_response['body'].read.return_value = json.dumps({
            'outputs': [{
                'text': json.dumps({
                    'response_text': 'We need more information.',
                    'confidence_score': 0.3,  # Low confidence
                    'reference_ids': [],
                    'compliance_checks': {},
                    'reasoning': 'Insufficient information'
                })
            }]
        }).encode('utf-8')

        with patch.object(claude_response.bedrock_runtime, 'invoke_model', return_value=mock_claude_response):
            result = claude_response.lambda_handler(response_event, lambda_context)

            assert result['statusCode'] == 200
            assert result['confidence_score'] < 0.5
            assert result['action'] == 'escalate'  # Should escalate, not auto-respond

    def test_workflow_error_recovery(
        self,
        lambda_env_vars,
        lambda_context,
        sample_email
    ):
        """Test that workflow handles errors gracefully"""

        # Simulate Bedrock API failure
        with patch.object(claude_response.bedrock_runtime, 'invoke_model', side_effect=Exception('API Error')):
            response_event = {
                'email_body': sample_email['body'],
                'subject': sample_email['subject'],
                'entities': {},
                'intent': 'unknown',
                'rag_documents': [],
                'crm_validation': {},
                'fraud_score': {}
            }

            result = claude_response.lambda_handler(response_event, lambda_context)

            # Should return error but not crash
            assert result['statusCode'] == 500
            assert 'error' in result
            assert result['action'] == 'escalate'


class TestMetricsCollection:
    """Integration tests for metrics collection across workflow"""

    def test_metrics_collected_during_inference(
        self,
        lambda_env_vars,
        dynamodb_tables,
        lambda_context
    ):
        """Test that metrics are properly collected during inference"""

        event = {
            'prompt': 'Test prompt for metrics',
            'task_type': 'test_task'
        }

        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = json.dumps({
            'outputs': [{'text': 'test_output'}]
        }).encode('utf-8')

        with patch.object(multi_llm.bedrock_runtime, 'invoke_model', return_value=mock_response):
            result = multi_llm.lambda_handler(event, lambda_context)

            # Verify metrics were stored
            table = dynamodb_tables['metrics']
            response = table.scan()

            assert response['Count'] > 0
            item = response['Items'][0]
            assert item['task_type'] == 'test_task'
            assert 'latency_ms' in item
            assert 'cost_usd' in item

    def test_metrics_aggregation(
        self,
        lambda_env_vars,
        dynamodb_tables,
        lambda_context,
        sample_model_metrics
    ):
        """Test metrics aggregation via evaluation_metrics"""

        # Add multiple metrics
        table = dynamodb_tables['metrics']
        for i in range(5):
            metric = sample_model_metrics.copy()
            metric['model_timestamp'] = f"mistral-7b#2026-03-04T10:{30+i}:00.000Z"
            table.put_item(Item=metric)

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/evaluation_metrics'))
        import lambda_function as eval_metrics

        event = {
            'task_type': 'all',
            'days': 7
        }

        result = eval_metrics.lambda_handler(event, lambda_context)

        assert result['statusCode'] == 200
        assert result['sample_count'] == 5
        stats = result['statistics']
        assert stats['total_requests'] == 5
        assert stats['success_rate'] == 1.0
