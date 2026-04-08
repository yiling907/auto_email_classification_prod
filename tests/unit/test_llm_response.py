"""
tests/unit/test_llm_response.py

Unit tests for the llm_response Lambda covering CoT generation and ReAct evaluation.
Run with:
    EMAIL_TABLE_NAME=test-emails MODEL_METRICS_TABLE_NAME=test-metrics \
    pytest tests/unit/test_llm_response.py -v
"""

import io
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Module isolation ──────────────────────────────────────────────────────────
os.environ.setdefault("EMAIL_TABLE_NAME", "test-emails")
os.environ.setdefault("MODEL_METRICS_TABLE_NAME", "test-metrics")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

_SHARED_DIR = os.path.join(os.path.dirname(__file__), '../../lambda/shared')
_LAMBDA_DIR  = os.path.join(os.path.dirname(__file__), '../../lambda/llm_response')

sys.path.insert(0, _SHARED_DIR)
sys.path.insert(0, _LAMBDA_DIR)


def _make_mistral_response(text: str) -> dict:
    body = json.dumps({"outputs": [{"text": text}]}).encode()
    return {"body": io.BytesIO(body)}


def _make_llama_response(text: str) -> dict:
    body = json.dumps({
        "generation": text,
        "prompt_token_count": 300,
        "generation_token_count": 80,
    }).encode()
    return {"body": io.BytesIO(body)}


# ── Tests for _parse_eval_scores ─────────────────────────────────────────────

class TestParseEvalScores:
    @pytest.fixture(autouse=True)
    def import_lambda(self):
        sys.path.insert(0, _LAMBDA_DIR)
        sys.path.insert(0, _SHARED_DIR)
        sys.modules.pop('lambda_function', None)
        with patch('boto3.client'), patch('boto3.resource'):
            import lambda_function as lf
            self.lf = lf

    def test_valid_json_parsed(self):
        raw = json.dumps({
            "faithfulness": 0.9, "answer_relevance": 0.8, "context_precision": 0.7,
            "context_recall": 0.6, "completeness": 0.85, "helpfulness": 0.75,
            "safety_compliance": 0.95, "no_harmful_advice": 1.0,
        })
        result = self.lf._parse_eval_scores(raw)
        assert result["faithfulness"] == pytest.approx(0.9)
        assert result["no_harmful_advice"] == pytest.approx(1.0)

    def test_react_final_answer_json_parsed(self):
        """Pre-extracted FINAL_ANSWER JSON (from evaluate_response) is parsed."""
        scores_json = json.dumps({
            "faithfulness": 0.8, "answer_relevance": 0.7, "context_precision": 0.6,
            "context_recall": 0.65, "completeness": 0.75, "helpfulness": 0.8,
            "safety_compliance": 0.9, "no_harmful_advice": 0.95,
        })
        result = self.lf._parse_eval_scores(scores_json)
        assert result["faithfulness"] == pytest.approx(0.8)

    def test_missing_field_defaults_to_0_5(self):
        raw = json.dumps({"faithfulness": 1.0})
        result = self.lf._parse_eval_scores(raw)
        assert result["answer_relevance"] == pytest.approx(0.5)

    def test_malformed_json_all_defaults(self):
        result = self.lf._parse_eval_scores("not json at all")
        assert all(v == pytest.approx(0.5) for v in result.values())

    def test_scores_clamped_to_0_1(self):
        raw = json.dumps({"faithfulness": 1.5, "answer_relevance": -0.3})
        result = self.lf._parse_eval_scores(raw)
        assert result["faithfulness"] == pytest.approx(1.0)
        assert result["answer_relevance"] == pytest.approx(0.0)


# ── Tests for generate_response (CoT path) ───────────────────────────────────

class TestGenerateResponse:
    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, _LAMBDA_DIR)
        sys.path.insert(0, _SHARED_DIR)
        sys.modules.pop('lambda_function', None)
        with patch('boto3.client') as mock_boto_client, \
             patch('boto3.resource'):
            self.mock_bedrock = MagicMock()
            mock_boto_client.return_value = self.mock_bedrock
            import lambda_function as lf
            self.lf = lf

    def test_cot_response_text_extracted_from_final_json(self):
        """response_text is extracted from FINAL_JSON when model follows CoT format."""
        cot_output = (
            "<reasoning>\n"
            "Step 1: Customer is asking about claim status.\n"
            "Step 2: CRM found, policy active, eligible.\n"
            "Step 5: Drafting response.\n"
            "</reasoning>\n"
            'FINAL_JSON: {"response_text": "Dear customer, your claim is being processed."}'
        )
        self.mock_bedrock.invoke_model.return_value = _make_mistral_response(cot_output)

        with patch.object(self.lf, '_store_metrics'):
            response_text, ref_ids, metrics, reasoning = self.lf.generate_response(
                "email-001", "Subject", "Body", "claim_status",
                [], {}, {}, "mistral-7b",
            )
        assert "Dear customer, your claim is being processed." in response_text
        assert "Best regards," in response_text
        assert "Laya Healthcare" in response_text
        assert "Step 1" in reasoning

    def test_fallback_to_raw_output_when_no_sentinel(self):
        """When FINAL_JSON: is absent, raw model output is used as response_text."""
        bare_output = "Dear customer, we have received your query."
        self.mock_bedrock.invoke_model.return_value = _make_mistral_response(bare_output)

        with patch.object(self.lf, '_store_metrics'):
            response_text, _, _, reasoning = self.lf.generate_response(
                "email-002", "Subject", "Body", "coverage_query",
                [], {}, {}, "mistral-7b",
            )
        assert bare_output in response_text
        assert "Best regards," in response_text
        assert "Laya Healthcare" in response_text
        assert bare_output in reasoning  # Falls back to raw output when no <reasoning> tags

    def test_max_tokens_is_3072_for_generation(self):
        """Bedrock is called with max_tokens=3072 for the generation task."""
        cot_output = 'FINAL_JSON: {"response_text": "Test response."}'
        self.mock_bedrock.invoke_model.return_value = _make_mistral_response(cot_output)

        with patch.object(self.lf, '_store_metrics'):
            self.lf.generate_response(
                "email-003", "S", "B", "other", [], {}, {}, "mistral-7b"
            )

        call_body = json.loads(self.mock_bedrock.invoke_model.call_args.kwargs.get(
            "body", self.mock_bedrock.invoke_model.call_args[1]["body"]
        ))
        assert call_body["max_tokens"] == 3072

    def test_returns_4_tuple(self):
        """generate_response now returns (response_text, reference_ids, metrics, reasoning)."""
        self.mock_bedrock.invoke_model.return_value = _make_mistral_response(
            'FINAL_JSON: {"response_text": "Hi"}'
        )
        with patch.object(self.lf, '_store_metrics'):
            result = self.lf.generate_response(
                "e", "s", "b", "other", [], {}, {}, "mistral-7b"
            )
        assert len(result) == 4


# ── Tests for evaluate_response (ReAct path) ─────────────────────────────────

class TestEvaluateResponse:
    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, _LAMBDA_DIR)
        sys.path.insert(0, _SHARED_DIR)
        sys.modules.pop('lambda_function', None)
        with patch('boto3.client') as mock_boto_client, \
             patch('boto3.resource'):
            self.mock_bedrock = MagicMock()
            mock_boto_client.return_value = self.mock_bedrock
            import lambda_function as lf
            self.lf = lf

    def test_react_evaluation_scores_parsed(self):
        """ReAct evaluation trace with FINAL_ANSWER is parsed into correct scores."""
        react_output = (
            "Thought 1: Response cites knowledge base correctly.\n"
            "Action 1: CHECK_FAITHFULNESS\n"
            "Observation 1: High faithfulness — no hallucination.\n"
            "Thought 2: Addresses claim status query directly.\n"
            "Action 2: CHECK_ANSWER_RELEVANCE\n"
            "Observation 2: High relevance.\n"
            "Thought 3-8: All pass.\n"
            'FINAL_ANSWER: {"faithfulness": 0.95, "answer_relevance": 0.90, '
            '"context_precision": 0.85, "context_recall": 0.80, '
            '"completeness": 0.88, "helpfulness": 0.92, '
            '"safety_compliance": 0.97, "no_harmful_advice": 1.0}'
        )
        self.mock_bedrock.invoke_model.return_value = _make_llama_response(react_output)

        with patch.object(self.lf, '_store_metrics'):
            eval_scores, confidence, metrics = self.lf.evaluate_response(
                "email-004", "Body", "Subject", [], {}, {},
                "Dear customer, your claim is being processed.", "llama-3.1-8b",
            )
        assert eval_scores["faithfulness"] == pytest.approx(0.95)
        assert eval_scores["no_harmful_advice"] == pytest.approx(1.0)
        assert 0.0 <= confidence <= 1.0

    def test_max_tokens_is_1024_for_evaluation(self):
        """Bedrock is called with max_tokens=1024 for the evaluation task."""
        scores_json = json.dumps({k: 0.8 for k in self.lf.EVAL_WEIGHTS})
        self.mock_bedrock.invoke_model.return_value = _make_llama_response(
            'FINAL_ANSWER: ' + scores_json
        )

        with patch.object(self.lf, '_store_metrics'):
            self.lf.evaluate_response(
                "e", "b", "s", [], {}, {}, "response", "llama-3.1-8b"
            )

        call_body = json.loads(self.mock_bedrock.invoke_model.call_args.kwargs.get(
            "body", self.mock_bedrock.invoke_model.call_args[1]["body"]
        ))
        assert call_body["max_gen_len"] == 1024

    def test_fallback_on_missing_sentinel(self):
        """Bare JSON without FINAL_ANSWER: still produces valid scores."""
        bare_scores = json.dumps({k: 0.7 for k in self.lf.EVAL_WEIGHTS})
        self.mock_bedrock.invoke_model.return_value = _make_llama_response(bare_scores)

        with patch.object(self.lf, '_store_metrics'):
            eval_scores, confidence, _ = self.lf.evaluate_response(
                "e", "b", "s", [], {}, {}, "response", "llama-3.1-8b"
            )
        assert all(v == pytest.approx(0.7) for v in eval_scores.values())


# ── Tests for _update_email_response (generation_reasoning stored) ────────────

class TestUpdateEmailResponse:
    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, _LAMBDA_DIR)
        sys.path.insert(0, _SHARED_DIR)
        sys.modules.pop('lambda_function', None)
        with patch('boto3.client'), patch('boto3.resource') as mock_boto_resource:
            self.mock_table = MagicMock()
            mock_instance = MagicMock()
            mock_boto_resource.return_value = mock_instance
            mock_instance.Table.return_value = self.mock_table
            import lambda_function as lf
            lf.email_table = self.mock_table
            self.lf = lf

    def test_generation_reasoning_stored(self):
        """generation_reasoning attribute is included in the DynamoDB update."""
        self.lf._update_email_response(
            "email-x", "Response text", [], "CoT reasoning here"
        )
        call_kwargs = self.mock_table.update_item.call_args.kwargs
        expr_vals = call_kwargs.get(
            "ExpressionAttributeValues",
            self.mock_table.update_item.call_args[1].get("ExpressionAttributeValues", {})
        )
        assert ":gr" in expr_vals
        assert expr_vals[":gr"] == "CoT reasoning here"

    def test_reasoning_truncated_at_3000(self):
        """generation_reasoning is truncated to 3000 chars before storage."""
        long_reasoning = "x" * 5000
        self.lf._update_email_response("e", "r", [], long_reasoning)
        call_kwargs = self.mock_table.update_item.call_args.kwargs
        expr_vals = call_kwargs.get(
            "ExpressionAttributeValues",
            self.mock_table.update_item.call_args[1].get("ExpressionAttributeValues", {})
        )
        assert len(expr_vals[":gr"]) == 3000

    def test_empty_reasoning_stored_as_empty_string(self):
        self.lf._update_email_response("e", "r", [], '')
        call_kwargs = self.mock_table.update_item.call_args.kwargs
        expr_vals = call_kwargs.get(
            "ExpressionAttributeValues",
            self.mock_table.update_item.call_args[1].get("ExpressionAttributeValues", {})
        )
        assert expr_vals[":gr"] == ''
