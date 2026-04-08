"""
tests/unit/test_crm_validation.py

Unit tests for the crm_validation Lambda focusing on the ReAct prompt changes.
Run with:
    EMAIL_TABLE_NAME=test-emails pytest tests/unit/test_crm_validation.py -v
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

# ── Module isolation ──────────────────────────────────────────────────────────
# crm_validation imports boto3 at module level, so we need to mock AWS before import.

os.environ.setdefault("CUSTOMERS_TABLE_NAME", "test-customers")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/crm_validation'))


def _make_bedrock_response(text: str) -> dict:
    """Build a mock Bedrock invoke_model response with Mistral output shape."""
    import io
    body = json.dumps({"outputs": [{"text": text}]}).encode()
    return {"body": io.BytesIO(body)}


# ── Tests for _parse_model_json (still works without ReAct) ──────────────────

_SHARED_DIR = os.path.join(os.path.dirname(__file__), '../../lambda/shared')
_LAMBDA_DIR  = os.path.join(os.path.dirname(__file__), '../../lambda/crm_validation')


class TestParseModelJson:
    @pytest.fixture(autouse=True)
    def import_lambda(self):
        sys.path.insert(0, _LAMBDA_DIR)
        sys.path.insert(0, _SHARED_DIR)
        sys.modules.pop('lambda_function', None)
        with patch('boto3.client'), patch('boto3.resource'):
            import lambda_function as lf
            self.lf = lf

    def test_parses_react_final_answer_json(self):
        json_str = '{"lookup_field": "customer_id", "lookup_value": "CUST-123456", "confidence": 0.95}'
        result = self.lf._parse_model_json(json_str)
        assert result["lookup_field"] == "customer_id"
        assert result["lookup_value"] == "CUST-123456"
        assert result["confidence"] == pytest.approx(0.95)

    def test_falls_back_to_json_block_when_no_sentinel(self):
        # Bare JSON without FINAL_ANSWER: sentinel
        raw = 'Model says: {"lookup_field": "email", "lookup_value": "test@test.com", "confidence": 0.7}'
        result = self.lf._parse_model_json(raw)
        assert result["lookup_field"] == "email"
        assert result["lookup_value"] == "test@test.com"

    def test_returns_null_plan_on_no_json(self):
        result = self.lf._parse_model_json("No JSON here at all.")
        assert result["lookup_field"] is None
        assert result["lookup_value"] is None
        assert result["confidence"] == 0.0

    def test_returns_null_plan_on_empty_input(self):
        result = self.lf._parse_model_json("")
        assert result["lookup_field"] is None

    def test_null_lookup_value_stored_as_none(self):
        result = self.lf._parse_model_json('{"lookup_field": null, "lookup_value": null, "confidence": 0.0}')
        assert result["lookup_field"] is None
        assert result["lookup_value"] is None


# ── Tests for _build_query_plan (ReAct path) ─────────────────────────────────

class TestBuildQueryPlanReAct:
    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, _LAMBDA_DIR)
        sys.path.insert(0, _SHARED_DIR)
        sys.modules.pop('lambda_function', None)
        with patch('boto3.client') as mock_boto_client, \
             patch('boto3.resource') as mock_boto_resource:
            self.mock_bedrock = MagicMock()
            mock_boto_client.return_value = self.mock_bedrock
            mock_boto_resource.return_value = MagicMock()
            import lambda_function as lf
            self.lf = lf

    def test_react_format_parsed_correctly(self):
        react_output = (
            "Thought 1: The extracted entities contain customer_id = CUST-001234.\n"
            "Action 1: SCAN_ENTITIES\n"
            "Observation 1: customer_id CUST-001234 matches CUST-XXXXXX format.\n"
            "Thought 2: No additional identifiers in email.\n"
            "Action 2: SCAN_EMAIL_EXCERPT\n"
            "Observation 2: None found.\n"
            "Thought 3: customer_id is the best identifier.\n"
            "Action 3: SELECT_BEST_IDENTIFIER\n"
            "Observation 3: Chose customer_id.\n"
            "Thought 4: Confidence 0.95 — exact format match.\n"
            "Action 4: ASSESS_CONFIDENCE\n"
            "Observation 4: High confidence.\n"
            'FINAL_ANSWER: {"lookup_field": "customer_id", "lookup_value": "CUST-001234", "confidence": 0.95}'
        )
        self.mock_bedrock.invoke_model.return_value = _make_bedrock_response(react_output)

        plan = self.lf._build_query_plan(
            intent="claim_status",
            email_body="My customer ID is CUST-001234.",
            entities={"customer_id": "CUST-001234"},
        )
        assert plan["lookup_field"] == "customer_id"
        assert plan["lookup_value"] == "CUST-001234"
        assert plan["confidence"] == pytest.approx(0.95)
        assert plan["react_scratchpad"] is not None
        assert "Thought 1" in plan["react_scratchpad"]

    def test_fallback_on_missing_sentinel(self):
        # Model ignores the sentinel — should fall back gracefully
        bare_output = '{"lookup_field": "member_id", "lookup_value": "MEM-000001", "confidence": 0.8}'
        self.mock_bedrock.invoke_model.return_value = _make_bedrock_response(bare_output)

        plan = self.lf._build_query_plan(
            intent="claim_status",
            email_body="My member ID is MEM-000001.",
            entities={"member_id": "MEM-000001"},
        )
        assert plan["lookup_field"] == "member_id"
        assert plan["lookup_value"] == "MEM-000001"
        # No scratchpad when sentinel missing
        assert plan["react_scratchpad"] is None

    def test_react_scratchpad_stored_in_plan(self):
        react_output = (
            "Thought 1: checking entities.\n"
            "Action 1: SCAN_ENTITIES\n"
            "Observation 1: policy_number found.\n"
            'FINAL_ANSWER: {"lookup_field": "policy_number", "lookup_value": "POL-IE-999999", "confidence": 0.9}'
        )
        self.mock_bedrock.invoke_model.return_value = _make_bedrock_response(react_output)

        plan = self.lf._build_query_plan(
            intent="policy_change",
            email_body="Policy POL-IE-999999",
            entities={"policy_number": "POL-IE-999999"},
        )
        assert "react_scratchpad" in plan
        assert plan["react_scratchpad"] is not None

    def test_scratchpad_truncated_to_500_chars(self):
        long_scratchpad = "Thought 1: " + "x" * 600 + "\n"
        react_output = (
            long_scratchpad
            + 'FINAL_ANSWER: {"lookup_field": null, "lookup_value": null, "confidence": 0.0}'
        )
        self.mock_bedrock.invoke_model.return_value = _make_bedrock_response(react_output)

        plan = self.lf._build_query_plan("other", "", {})
        assert len(plan["react_scratchpad"]) <= 500

    def test_max_tokens_is_384(self):
        """Verify the Bedrock call uses max_tokens=384 (not the old 128)."""
        self.mock_bedrock.invoke_model.return_value = _make_bedrock_response(
            '{"lookup_field": null, "lookup_value": null, "confidence": 0.0}'
        )
        self.lf._build_query_plan("other", "email text", {})

        call_args = self.mock_bedrock.invoke_model.call_args
        body = json.loads(call_args.kwargs.get("body") or call_args.args[0] if call_args.args else call_args.kwargs["body"])
        assert body["max_tokens"] == 384

    def test_model_failure_returns_null_plan(self):
        self.mock_bedrock.invoke_model.side_effect = Exception("Bedrock timeout")
        plan = self.lf._build_query_plan("other", "email text", {})
        assert plan["lookup_field"] is None
        assert plan["lookup_value"] is None
        assert plan["confidence"] == 0.0


# ── Tests for _sanitise (unchanged, regression guard) ────────────────────────

class TestSanitise:
    @pytest.fixture(autouse=True)
    def import_lambda(self):
        sys.path.insert(0, _LAMBDA_DIR)
        sys.path.insert(0, _SHARED_DIR)
        sys.modules.pop('lambda_function', None)
        with patch('boto3.client'), patch('boto3.resource'):
            import lambda_function as lf
            self.lf = lf

    def test_valid_customer_id(self):
        f, v = self.lf._sanitise("customer_id", "CUST-123456")
        assert f == "customer_id"
        assert v == "CUST-123456"

    def test_invalid_field_rejected(self):
        f, v = self.lf._sanitise("full_name", "John")
        assert f is None
        assert v is None

    def test_malformed_value_rejected(self):
        f, v = self.lf._sanitise("customer_id", "INVALID")
        assert f is None
        assert v is None

    def test_valid_email(self):
        f, v = self.lf._sanitise("email", "user@example.com")
        assert f == "email"
        assert v == "user@example.com"
