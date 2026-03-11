"""
Integration tests for end-to-end email processing workflow
"""
import json
import sys
import os
from unittest.mock import patch, MagicMock
import pytest

sys.modules.pop('lambda_function', None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/email_parser'))
import lambda_function as email_parser

sys.modules.pop('lambda_function', None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/classify_intent'))
import lambda_function as multi_llm

sys.modules.pop('lambda_function', None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/rag_retrieval'))
import lambda_function as rag_retrieval

sys.modules.pop('lambda_function', None)
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
        assert parsed_result['parsed_data']['sender_email'] == sample_email['sender_email']
        assert parsed_result['parsed_data']['body_text'] != ''

        # Step 2: Email Classification (classify_intent)
        clf_json = json.dumps({
            'customer_intent': 'claim_status', 'secondary_intent': '',
            'business_line': 'health_insurance', 'urgency': 'medium',
            'sentiment': 'frustrated', 'gold_route_team': 'claims_team',
            'gold_priority': 'normal', 'requires_human_review': False,
        })
        acc_json = json.dumps({f: 1 for f in (
            'customer_intent', 'secondary_intent', 'business_line',
            'urgency', 'sentiment', 'gold_route_team', 'gold_priority')})
        intent_event = {
            'email_id': parsed_result['email_id'],
            'email_body': sample_email['body_text'],
            'subject': sample_email['subject'],
        }
        # classify call (mistral) then accuracy call (llama)
        side_effects = [
            {'body': MagicMock(read=lambda: json.dumps(
                {'outputs': [{'text': clf_json}]}).encode('utf-8'))},
            {'body': MagicMock(read=lambda: json.dumps({
                'generation': acc_json,
                'prompt_token_count': 200, 'generation_token_count': 50,
            }).encode('utf-8'))},
        ]

        with patch.object(multi_llm.bedrock_runtime, 'invoke_model', side_effect=side_effects):
            intent_result = multi_llm.lambda_handler(intent_event, lambda_context)

            assert intent_result['statusCode'] == 200
            assert intent_result['classification']['customer_intent'] == 'claim_status'

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

        # Step 4: Response Generation + Evaluation
        # Call 1: mistral drafts response; Call 2: llama evaluates across 8 dimensions
        high_eval = json.dumps({
            'faithfulness': 0.9, 'answer_relevance': 0.9, 'context_precision': 0.9,
            'context_recall': 0.9, 'completeness': 0.9, 'helpfulness': 0.9,
            'safety_compliance': 0.9, 'no_harmful_advice': 0.9,
        })
        response_side_effects = [
            # Generation (mistral) — outputs format
            {'body': MagicMock(read=lambda: json.dumps({'outputs': [{'text': json.dumps({
                'response_text': 'Thank you for your inquiry about your claim.',
                'reference_ids': ['policy_001'],
            })}]}).encode('utf-8'))},
            # Evaluation (llama) — generation format
            {'body': MagicMock(read=lambda: json.dumps({
                'generation': high_eval,
                'prompt_token_count': 300, 'generation_token_count': 60,
            }).encode('utf-8'))},
        ]

        response_event = {
            'email_id': parsed_result['email_id'],
            'email_body': sample_email['body_text'],
            'subject': sample_email['subject'],
            'rag_documents': rag_result['retrieved_documents'],
            'classification': {'customer_intent': 'claim_status'},
            'crm_validation': {'policy_exists': True, 'customer_id': 'CUST-001'},
            'fraud_score': {'risk_level': 'low', 'risk_score': 0.1},
        }

        with patch.object(claude_response.bedrock_runtime, 'invoke_model', side_effect=response_side_effects):
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
        """Test workflow when evaluation scores are low (should escalate)"""

        low_eval = json.dumps({
            'faithfulness': 0.2, 'answer_relevance': 0.2, 'context_precision': 0.2,
            'context_recall': 0.2, 'completeness': 0.2, 'helpfulness': 0.2,
            'safety_compliance': 0.2, 'no_harmful_advice': 0.2,
        })
        side_effects = [
            {'body': MagicMock(read=lambda: json.dumps({'outputs': [{'text': json.dumps({
                'response_text': 'We need more information.',
                'reference_ids': [],
            })}]}).encode('utf-8'))},
            {'body': MagicMock(read=lambda: json.dumps({
                'generation': low_eval,
                'prompt_token_count': 200, 'generation_token_count': 40,
            }).encode('utf-8'))},
        ]

        response_event = {
            'email_body': sample_email['body_text'],
            'subject': sample_email['subject'],
            'rag_documents': [],
            'classification': {'customer_intent': 'other'},
            'crm_validation': {},
            'fraud_score': {'risk_level': 'high', 'risk_score': 0.85},
        }

        with patch.object(claude_response.bedrock_runtime, 'invoke_model', side_effect=side_effects):
            result = claude_response.lambda_handler(response_event, lambda_context)

            assert result['statusCode'] == 200
            assert result['confidence_score'] < 0.5
            assert result['action'] == 'escalate'

    def test_workflow_error_recovery(
        self,
        lambda_env_vars,
        lambda_context,
        sample_email
    ):
        """Test that workflow handles errors gracefully"""

        with patch.object(claude_response.bedrock_runtime, 'invoke_model', side_effect=Exception('API Error')):
            response_event = {
                'email_body': sample_email['body_text'],
                'subject': sample_email['subject'],
                'rag_documents': [],
                'classification': {},
                'crm_validation': {},
                'fraud_score': {},
            }

            result = claude_response.lambda_handler(response_event, lambda_context)

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

        clf_json = json.dumps({
            'customer_intent': 'claim_status', 'secondary_intent': '',
            'business_line': 'health_insurance', 'urgency': 'low',
            'sentiment': 'neutral', 'gold_route_team': 'claims_team',
            'gold_priority': 'normal', 'requires_human_review': False,
        })
        acc_json = json.dumps({f: 1 for f in (
            'customer_intent', 'secondary_intent', 'business_line',
            'urgency', 'sentiment', 'gold_route_team', 'gold_priority')})

        side_effects = [
            {'body': MagicMock(read=lambda: json.dumps(
                {'outputs': [{'text': clf_json}]}).encode('utf-8'))},
            {'body': MagicMock(read=lambda: json.dumps({
                'generation': acc_json,
                'prompt_token_count': 200, 'generation_token_count': 50,
            }).encode('utf-8'))},
        ]

        event = {
            'email_id': 'integ-test-001',
            'email_body': 'I need help with my claim.',
            'subject': 'Claim query',
        }

        with patch.object(multi_llm.bedrock_runtime, 'invoke_model', side_effect=side_effects):
            result = multi_llm.lambda_handler(event, lambda_context)

            # Verify metrics were stored (classification + accuracy = 2 records)
            table = dynamodb_tables['metrics']
            response = table.scan()

            assert response['Count'] == 2
            task_types = {item['task_type'] for item in response['Items']}
            assert 'email_classification' in task_types
            assert 'accuracy_evaluation' in task_types
            item = next(i for i in response['Items']
                        if i['task_type'] == 'email_classification')
            assert 'latency_ms' in item
            assert 'cost_usd' in item
