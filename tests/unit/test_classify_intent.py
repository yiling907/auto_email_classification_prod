"""
Unit tests for classify_intent Lambda function.
Covers classification, accuracy evaluation, output parsers, metrics storage,
model invocation, and the lambda_handler toggle logic.
"""
import json
import sys
import os
from decimal import Decimal
from unittest.mock import patch, MagicMock
import pytest
from moto import mock_aws
import boto3

# Clear any cached lambda_function module from other test files
sys.modules.pop('lambda_function', None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/classify_intent'))
import lambda_function as lf


# ── Shared helpers ────────────────────────────────────────────────────────────

SAMPLE_BODY = (
    'I submitted my hospital claim for POL-IE-123456 two weeks ago '
    'and have not received any update. Please advise.'
)
SAMPLE_SUBJECT = 'Claim status enquiry'
SAMPLE_EMAIL_ID = 'email-test-001'

VALID_CLASSIFICATION = {
    'customer_intent': 'claim_status',
    'secondary_intent': '',
    'business_line': 'health_insurance',
    'urgency': 'medium',
    'sentiment': 'frustrated',
    'gold_route_team': 'claims_team',
    'gold_priority': 'normal',
    'requires_human_review': False,
}

def _make_mistral_response(text: str) -> dict:
    mock = {'body': MagicMock()}
    mock['body'].read.return_value = json.dumps(
        {'outputs': [{'text': text}]}
    ).encode('utf-8')
    return mock

def _make_llama_response(text: str) -> dict:
    mock = {'body': MagicMock()}
    mock['body'].read.return_value = json.dumps({
        'generation': text,
        'prompt_token_count': 300,
        'generation_token_count': 80,
    }).encode('utf-8')
    return mock


# ── _parse_classification ─────────────────────────────────────────────────────

class TestParseClassification:

    def test_valid_json_parsed_correctly(self):
        raw = json.dumps({
            'customer_intent': 'claim_status',
            'secondary_intent': '',
            'business_line': 'health_insurance',
            'urgency': 'medium',
            'sentiment': 'frustrated',
            'gold_route_team': 'claims_team',
            'gold_priority': 'normal',
            'requires_human_review': False,
        })
        result = lf._parse_classification(raw)
        assert result['customer_intent'] == 'claim_status'
        assert result['gold_route_team'] == 'claims_team'
        assert result['business_line'] == 'health_insurance'

    def test_invalid_intent_falls_back_to_other(self):
        raw = json.dumps({'customer_intent': 'nonsense_value'})
        assert lf._parse_classification(raw)['customer_intent'] == 'other'

    def test_invalid_urgency_falls_back_to_low(self):
        raw = json.dumps({'customer_intent': 'claim_status', 'urgency': 'critical'})
        assert lf._parse_classification(raw)['urgency'] == 'low'

    def test_invalid_sentiment_falls_back_to_neutral(self):
        raw = json.dumps({'customer_intent': 'claim_status', 'sentiment': 'angry'})
        assert lf._parse_classification(raw)['sentiment'] == 'neutral'

    def test_invalid_route_team_inferred_from_intent(self):
        raw = json.dumps({'customer_intent': 'claim_status', 'gold_route_team': 'bad_team'})
        assert lf._parse_classification(raw)['gold_route_team'] == 'claims_team'

    def test_invalid_priority_falls_back_to_normal(self):
        raw = json.dumps({'customer_intent': 'claim_status', 'gold_priority': 'critical'})
        assert lf._parse_classification(raw)['gold_priority'] == 'normal'

    def test_complaint_forces_human_review(self):
        raw = json.dumps({'customer_intent': 'complaint', 'requires_human_review': False})
        assert lf._parse_classification(raw)['requires_human_review'] is True

    def test_pre_authorisation_forces_human_review(self):
        raw = json.dumps({'customer_intent': 'pre_authorisation'})
        assert lf._parse_classification(raw)['requires_human_review'] is True

    def test_urgent_priority_forces_human_review(self):
        raw = json.dumps({'customer_intent': 'claim_status', 'gold_priority': 'urgent'})
        assert lf._parse_classification(raw)['requires_human_review'] is True

    def test_markdown_fences_stripped(self):
        raw = '```json\n{"customer_intent": "payment_issue"}\n```'
        result = lf._parse_classification(raw)
        assert result['customer_intent'] == 'payment_issue'

    def test_malformed_json_returns_safe_defaults(self):
        result = lf._parse_classification('not json at all')
        assert result['customer_intent'] == 'other'
        assert result['business_line'] == 'health_insurance'

    def test_business_line_always_health_insurance(self):
        raw = json.dumps({'customer_intent': 'renewal_query', 'business_line': 'life_insurance'})
        assert lf._parse_classification(raw)['business_line'] == 'health_insurance'


# ── _parse_accuracy ───────────────────────────────────────────────────────────

class TestParseAccuracy:

    def test_all_ones_parsed(self):
        raw = json.dumps({f: 1 for f in lf.CLASSIFICATION_FIELDS})
        result = lf._parse_accuracy(raw)
        assert all(v == 1 for v in result.values())

    def test_all_zeros_parsed(self):
        raw = json.dumps({f: 0 for f in lf.CLASSIFICATION_FIELDS})
        result = lf._parse_accuracy(raw)
        assert all(v == 0 for v in result.values())

    def test_missing_field_defaults_to_zero(self):
        raw = json.dumps({'customer_intent': 1})   # other fields missing
        result = lf._parse_accuracy(raw)
        assert result['customer_intent'] == 1
        assert result['urgency'] == 0

    def test_malformed_json_all_zeros(self):
        result = lf._parse_accuracy('not valid json')
        assert all(v == 0 for v in result.values())

    def test_markdown_fences_stripped(self):
        raw = '```json\n{"customer_intent": 1, "secondary_intent": 1, "business_line": 1, "urgency": 1, "sentiment": 1, "gold_route_team": 1, "gold_priority": 1}\n```'
        result = lf._parse_accuracy(raw)
        assert result['customer_intent'] == 1


# ── _calculate_cost ───────────────────────────────────────────────────────────

class TestCalculateCost:

    def test_mistral_cost(self):
        cfg = lf.MODELS['mistral-7b']
        cost = lf._calculate_cost(1000, 200, cfg)
        expected = 1.0 * 0.00015 + 0.2 * 0.00020
        assert abs(cost - expected) < 1e-8

    def test_zero_tokens_zero_cost(self):
        cfg = lf.MODELS['llama-3.1-8b']
        assert lf._calculate_cost(0, 0, cfg) == 0.0


# ── _other_model ──────────────────────────────────────────────────────────────

class TestOtherModel:

    def test_other_of_mistral_is_llama(self):
        assert lf._other_model('mistral-7b') == 'llama-3.1-8b'

    def test_other_of_llama_is_mistral(self):
        assert lf._other_model('llama-3.1-8b') == 'mistral-7b'


# ── _invoke_model ─────────────────────────────────────────────────────────────

class TestInvokeModel:

    def test_mistral_output_extracted(self):
        cfg = lf.MODELS['mistral-7b']
        with patch.object(lf.bedrock_runtime, 'invoke_model',
                          return_value=_make_mistral_response('{"customer_intent":"claim_status"}')):
            text, inp, out = lf._invoke_model(cfg, 'hello prompt')
        assert 'claim_status' in text
        assert inp > 0
        assert out > 0

    def test_llama_output_extracted(self):
        cfg = lf.MODELS['llama-3.1-8b']
        with patch.object(lf.bedrock_runtime, 'invoke_model',
                          return_value=_make_llama_response('{"customer_intent":"renewal_query"}')):
            text, inp, out = lf._invoke_model(cfg, 'hello prompt')
        assert 'renewal_query' in text
        assert inp == 300
        assert out == 80

    def test_bedrock_error_propagates(self):
        cfg = lf.MODELS['mistral-7b']
        with patch.object(lf.bedrock_runtime, 'invoke_model',
                          side_effect=Exception('Throttled')):
            with pytest.raises(Exception, match='Throttled'):
                lf._invoke_model(cfg, 'prompt')


# ── _store_metrics ────────────────────────────────────────────────────────────

class TestStoreMetrics:

    @mock_aws
    def test_metrics_written_to_dynamodb(self, lambda_env_vars):
        dynamo = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamo.create_table(
            TableName='test-model-metrics',
            KeySchema=[{'AttributeName': 'metric_key', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'metric_key', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )

        lf._store_metrics({
            'model_id':   'mistral.mistral-7b-instruct-v0:2',
            'model_name': 'mistral-7b',
            'email_id':   SAMPLE_EMAIL_ID,
            'task_type':  'email_classification',
            'cost_usd':   0.000123,
            'latency_ms': 1234.5,
            'timestamp':  '2026-03-10T12:00:00Z',
        })

        items = table.scan()['Items']
        assert len(items) == 1
        item = items[0]
        assert item['metric_key'] == (
            f'mistral.mistral-7b-instruct-v0:2#email_classification#{SAMPLE_EMAIL_ID}'
        )
        assert item['model_name'] == 'mistral-7b'
        assert isinstance(item['cost_usd'], Decimal)
        assert isinstance(item['latency_ms'], Decimal)

    @mock_aws
    def test_accuracy_scores_stored(self, lambda_env_vars):
        dynamo = boto3.resource('dynamodb', region_name='us-east-1')
        dynamo.create_table(
            TableName='test-model-metrics',
            KeySchema=[{'AttributeName': 'metric_key', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'metric_key', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )

        lf._store_metrics({
            'model_id':        'meta.llama3-8b-instruct-v1:0',
            'model_name':      'llama-3.1-8b',
            'email_id':        SAMPLE_EMAIL_ID,
            'task_type':       'accuracy_evaluation',
            'cost_usd':        0.000050,
            'latency_ms':      900.0,
            'timestamp':       '2026-03-10T12:00:00Z',
            'accuracy_scores': {'customer_intent': 1, 'urgency': 0},
            'overall_accuracy': 0.5,
        })

        items = boto3.resource('dynamodb', region_name='us-east-1') \
                     .Table('test-model-metrics').scan()['Items']
        assert len(items) == 1
        assert 'accuracy_scores' in items[0]
        assert isinstance(items[0]['overall_accuracy'], Decimal)


# ── classify_email ────────────────────────────────────────────────────────────

class TestClassifyEmail:

    def test_classify_email_mistral_success(self, lambda_env_vars):
        clf_json = json.dumps(VALID_CLASSIFICATION)
        with patch.object(lf.bedrock_runtime, 'invoke_model',
                          return_value=_make_mistral_response(clf_json)):
            with patch.object(lf, '_store_metrics'):
                clf, metrics = lf.classify_email(
                    SAMPLE_EMAIL_ID, SAMPLE_SUBJECT, SAMPLE_BODY, 'mistral-7b'
                )
        assert clf['customer_intent'] == 'claim_status'
        assert clf['business_line'] == 'health_insurance'
        assert metrics['model_name'] == 'mistral-7b'
        assert metrics['task_type'] == 'email_classification'
        assert metrics['email_id'] == SAMPLE_EMAIL_ID
        assert metrics['cost_usd'] >= 0
        assert metrics['latency_ms'] >= 0

    def test_classify_email_llama_success(self, lambda_env_vars):
        clf_json = json.dumps(VALID_CLASSIFICATION)
        with patch.object(lf.bedrock_runtime, 'invoke_model',
                          return_value=_make_llama_response(clf_json)):
            with patch.object(lf, '_store_metrics'):
                clf, metrics = lf.classify_email(
                    SAMPLE_EMAIL_ID, SAMPLE_SUBJECT, SAMPLE_BODY, 'llama-3.1-8b'
                )
        assert clf['customer_intent'] == 'claim_status'
        assert metrics['model_name'] == 'llama-3.1-8b'

    def test_classify_email_stores_metrics(self, lambda_env_vars):
        clf_json = json.dumps(VALID_CLASSIFICATION)
        with patch.object(lf.bedrock_runtime, 'invoke_model',
                          return_value=_make_mistral_response(clf_json)):
            with patch.object(lf, '_store_metrics') as mock_store:
                lf.classify_email(SAMPLE_EMAIL_ID, SAMPLE_SUBJECT, SAMPLE_BODY, 'mistral-7b')
        mock_store.assert_called_once()
        stored = mock_store.call_args[0][0]
        assert stored['model_id'] == lf.MODELS['mistral-7b']['id']


# ── evaluate_accuracy ─────────────────────────────────────────────────────────

class TestEvaluateAccuracy:

    def test_evaluate_accuracy_returns_per_field_scores(self, lambda_env_vars):
        scores = {f: 1 for f in lf.CLASSIFICATION_FIELDS}
        with patch.object(lf.bedrock_runtime, 'invoke_model',
                          return_value=_make_llama_response(json.dumps(scores))):
            with patch.object(lf, '_store_metrics'):
                result = lf.evaluate_accuracy(
                    SAMPLE_EMAIL_ID, SAMPLE_SUBJECT, SAMPLE_BODY,
                    VALID_CLASSIFICATION, 'llama-3.1-8b'
                )
        assert result['judge_model'] == 'llama-3.1-8b'
        assert all(v == 1 for v in result['per_field'].values())
        assert result['overall_score'] == 1.0

    def test_evaluate_accuracy_partial_scores(self, lambda_env_vars):
        scores = {f: (1 if i % 2 == 0 else 0)
                  for i, f in enumerate(lf.CLASSIFICATION_FIELDS)}
        with patch.object(lf.bedrock_runtime, 'invoke_model',
                          return_value=_make_mistral_response(json.dumps(scores))):
            with patch.object(lf, '_store_metrics'):
                result = lf.evaluate_accuracy(
                    SAMPLE_EMAIL_ID, SAMPLE_SUBJECT, SAMPLE_BODY,
                    VALID_CLASSIFICATION, 'mistral-7b'
                )
        assert 0.0 < result['overall_score'] < 1.0


# ── lambda_handler ────────────────────────────────────────────────────────────

class TestLambdaHandler:

    def _mock_both_models(self, clf_text, acc_text):
        """Return side_effect list: first call = classifier, second = judge."""
        return [
            _make_mistral_response(clf_text),
            _make_llama_response(acc_text),
        ]

    def test_handler_success_default_model(self, lambda_env_vars, lambda_context):
        clf_json = json.dumps(VALID_CLASSIFICATION)
        acc_json = json.dumps({f: 1 for f in lf.CLASSIFICATION_FIELDS})
        side_effects = self._mock_both_models(clf_json, acc_json)

        with patch.object(lf.bedrock_runtime, 'invoke_model', side_effect=side_effects):
            with patch.object(lf, '_store_metrics'):
                with patch.object(lf, '_update_email_record'):
                    result = lf.lambda_handler(
                        {'email_id': SAMPLE_EMAIL_ID,
                         'email_body': SAMPLE_BODY,
                         'subject': SAMPLE_SUBJECT},
                        lambda_context,
                    )
        assert result['statusCode'] == 200
        assert result['active_model'] == 'mistral-7b'
        clf = result['classification']
        assert clf['customer_intent'] == 'claim_status'
        assert clf['business_line'] == 'health_insurance'
        assert 'metrics' in result
        assert 'accuracy_evaluation' in result
        assert result['accuracy_evaluation']['judge_model'] == 'llama-3.1-8b'

    def test_handler_model_toggle_to_llama(self, lambda_env_vars, lambda_context):
        clf_json = json.dumps(VALID_CLASSIFICATION)
        acc_json = json.dumps({f: 1 for f in lf.CLASSIFICATION_FIELDS})
        side_effects = [
            _make_llama_response(clf_json),
            _make_mistral_response(acc_json),
        ]

        with patch.object(lf.bedrock_runtime, 'invoke_model', side_effect=side_effects):
            with patch.object(lf, '_store_metrics'):
                with patch.object(lf, '_update_email_record'):
                    result = lf.lambda_handler(
                        {'email_id': SAMPLE_EMAIL_ID,
                         'email_body': SAMPLE_BODY,
                         'active_model': 'llama-3.1-8b'},
                        lambda_context,
                    )
        assert result['statusCode'] == 200
        assert result['active_model'] == 'llama-3.1-8b'
        assert result['accuracy_evaluation']['judge_model'] == 'mistral-7b'

    def test_handler_missing_email_body_returns_500(self, lambda_env_vars, lambda_context):
        result = lf.lambda_handler({'email_id': 'x'}, lambda_context)
        assert result['statusCode'] == 500
        assert 'Missing email_body' in result['error']

    def test_handler_unknown_model_returns_500(self, lambda_env_vars, lambda_context):
        result = lf.lambda_handler(
            {'email_id': 'x', 'email_body': 'hi', 'active_model': 'gpt-99'},
            lambda_context,
        )
        assert result['statusCode'] == 500
        assert 'Unknown model' in result['error']

    def test_handler_updates_email_record(self, lambda_env_vars, lambda_context):
        clf_json = json.dumps(VALID_CLASSIFICATION)
        acc_json = json.dumps({f: 1 for f in lf.CLASSIFICATION_FIELDS})
        side_effects = self._mock_both_models(clf_json, acc_json)

        with patch.object(lf.bedrock_runtime, 'invoke_model', side_effect=side_effects):
            with patch.object(lf, '_store_metrics'):
                with patch.object(lf, '_update_email_record') as mock_update:
                    lf.lambda_handler(
                        {'email_id': SAMPLE_EMAIL_ID,
                         'email_body': SAMPLE_BODY},
                        lambda_context,
                    )
        mock_update.assert_called_once_with(SAMPLE_EMAIL_ID, VALID_CLASSIFICATION)

    def test_handler_stores_two_metrics_records(self, lambda_env_vars, lambda_context):
        """One for classification, one for accuracy evaluation."""
        clf_json = json.dumps(VALID_CLASSIFICATION)
        acc_json = json.dumps({f: 1 for f in lf.CLASSIFICATION_FIELDS})
        side_effects = self._mock_both_models(clf_json, acc_json)

        with patch.object(lf.bedrock_runtime, 'invoke_model', side_effect=side_effects):
            with patch.object(lf, '_store_metrics') as mock_store:
                with patch.object(lf, '_update_email_record'):
                    lf.lambda_handler(
                        {'email_id': SAMPLE_EMAIL_ID, 'email_body': SAMPLE_BODY},
                        lambda_context,
                    )
        assert mock_store.call_count == 2
        task_types = {c[0][0]['task_type'] for c in mock_store.call_args_list}
        assert task_types == {'email_classification', 'accuracy_evaluation'}
