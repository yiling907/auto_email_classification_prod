"""
tests/unit/test_extract_entity.py

Unit tests for the extract_entity Lambda focusing on the CoT prompt changes.
Run with:
    EMAIL_TABLE_NAME=test-emails pytest tests/unit/test_extract_entity.py -v
"""

import io
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Module isolation ──────────────────────────────────────────────────────────
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

_SHARED_DIR = os.path.join(os.path.dirname(__file__), '../../lambda/shared')
_LAMBDA_DIR  = os.path.join(os.path.dirname(__file__), '../../lambda/extract_entity')

sys.path.insert(0, _SHARED_DIR)
sys.path.insert(0, _LAMBDA_DIR)


def _make_bedrock_response(text: str) -> dict:
    body = json.dumps({"outputs": [{"text": text}]}).encode()
    return {"body": io.BytesIO(body)}


# ── Tests for _parse_extraction_json ─────────────────────────────────────────

class TestParseExtractionJson:
    @pytest.fixture(autouse=True)
    def import_lambda(self):
        sys.path.insert(0, _LAMBDA_DIR)
        sys.path.insert(0, _SHARED_DIR)
        sys.modules.pop('lambda_function', None)
        with patch('boto3.client'), patch('boto3.resource'):
            import lambda_function as lf
            self.lf = lf

    def test_cot_final_json_sentinel_parsed(self):
        """FINAL_JSON: sentinel is extracted and parsed correctly."""
        cot_output = (
            "<reasoning>\n"
            "SECTION 1: membership_no LH-001234 found, surname Smith found.\n"
            "SECTION 6: two receipts totalling €150.\n"
            "Confidence: 0.8 — several fields present.\n"
            "</reasoning>\n"
            'FINAL_JSON: {"membership_no": "LH-001234", "surname": "Smith", '
            '"dependants": [], "receipts": [], "receipts_total_cost": 150.0, '
            '"doc_category": "claim_form", "confidence": 0.8}'
        )
        fields, confidence = self.lf._parse_extraction_json(cot_output, "test-001")
        assert fields.get("membership_no") == "LH-001234"
        assert fields.get("surname") == "Smith"
        assert confidence == pytest.approx(0.8)

    def test_confidence_from_model_not_hardcoded(self):
        """Confidence is extracted from model output, not a hardcoded default."""
        cot_output = (
            "<reasoning>Only declaration_date found. Low confidence.</reasoning>\n"
            'FINAL_JSON: {"declaration_date": "2026-01-15", "dependants": [], '
            '"receipts": [], "doc_category": "claim_form", "confidence": 0.25}'
        )
        _, confidence = self.lf._parse_extraction_json(cot_output, "test-002")
        # Confidence should reflect the model's assessment (0.25), not a hardcoded value
        assert confidence == pytest.approx(0.25)

    def test_fallback_on_missing_sentinel(self):
        """When FINAL_JSON: is absent, brace-depth extraction is used as fallback."""
        bare_output = (
            '{"membership_no": "LH-999999", "dependants": [], "receipts": [], '
            '"doc_category": "claim_form", "confidence": 0.6}'
        )
        fields, confidence = self.lf._parse_extraction_json(bare_output, "test-003")
        assert fields.get("membership_no") == "LH-999999"
        assert confidence == pytest.approx(0.6)

    def test_reasoning_tags_logged(self, caplog):
        """CoT reasoning section is captured and logged."""
        import logging
        cot_output = (
            "<reasoning>\nSection 1: surname Jones found.\n</reasoning>\n"
            'FINAL_JSON: {"surname": "Jones", "dependants": [], "receipts": [], '
            '"doc_category": "claim_form", "confidence": 0.7}'
        )
        with caplog.at_level(logging.INFO):
            self.lf._parse_extraction_json(cot_output, "test-004")
        # Should log a reasoning trace record
        log_text = ' '.join(caplog.messages)
        assert 'extract_entity' in log_text or 'test-004' in log_text

    def test_no_json_returns_empty_dict_and_low_confidence(self):
        """Complete failure to find JSON returns ({}, 0.5)."""
        fields, confidence = self.lf._parse_extraction_json("No JSON here at all.", "test-005")
        assert fields == {}
        assert confidence == pytest.approx(0.5)

    def test_malformed_json_returns_empty_dict(self):
        """Malformed JSON after FINAL_JSON: returns ({}, 0.5)."""
        cot_output = '<reasoning>ok</reasoning>\nFINAL_JSON: {bad json here'
        fields, confidence = self.lf._parse_extraction_json(cot_output, "test-006")
        assert fields == {}
        assert confidence == pytest.approx(0.5)

    def test_null_scalar_values_stripped(self):
        """null and empty-string scalar fields are removed from the output dict."""
        cot_output = (
            'FINAL_JSON: {"membership_no": null, "surname": "Brown", '
            '"forenames": "", "dependants": [], "receipts": [], '
            '"doc_category": "claim_form", "confidence": 0.5}'
        )
        fields, _ = self.lf._parse_extraction_json(cot_output, "test-007")
        assert "membership_no" not in fields  # null stripped
        assert "forenames" not in fields       # empty string stripped
        assert fields.get("surname") == "Brown"
        assert fields.get("dependants") == []  # empty array kept

    def test_boolean_false_values_kept(self):
        """Boolean False values are kept (not stripped as falsy)."""
        cot_output = (
            'FINAL_JSON: {"expenses_recoverable": false, "dependants": [], '
            '"receipts": [], "doc_category": "claim_form", "confidence": 0.6}'
        )
        fields, _ = self.lf._parse_extraction_json(cot_output, "test-008")
        assert fields.get("expenses_recoverable") is False


# ── Tests for _extract_via_bedrock (CoT path) ─────────────────────────────────

class TestExtractViaBedrock:
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

    def test_max_tokens_is_3072(self):
        """Verify the Bedrock call uses max_tokens=3072 (increased for CoT)."""
        cot_output = (
            'FINAL_JSON: {"dependants": [], "receipts": [], '
            '"doc_category": "claim_form", "confidence": 0.5}'
        )
        self.mock_bedrock.invoke_model.return_value = _make_bedrock_response(cot_output)

        self.lf._extract_via_bedrock("Subject", "Body text", [], "test-e01")

        call_args = self.mock_bedrock.invoke_model.call_args
        body = json.loads(call_args.kwargs.get("body") or call_args[1].get("body", "{}"))
        assert body["max_tokens"] == 3072

    def test_cot_output_parsed_correctly(self):
        """Full CoT output is parsed and returned with correct fields and confidence."""
        cot_output = (
            "<reasoning>\nSection 1: membership LH-X found.\n</reasoning>\n"
            'FINAL_JSON: {"membership_no": "LH-X", "dependants": [], '
            '"receipts": [], "doc_category": "claim_form", "confidence": 0.85}'
        )
        self.mock_bedrock.invoke_model.return_value = _make_bedrock_response(cot_output)

        fields, confidence, was_called = self.lf._extract_via_bedrock(
            "Subject", "Body", [], "test-e02"
        )
        assert fields.get("membership_no") == "LH-X"
        assert confidence == pytest.approx(0.85)
        assert was_called is True

    def test_bedrock_failure_returns_empty_fields(self):
        """Bedrock exception returns ({}, 0.5, False) — never raises."""
        self.mock_bedrock.invoke_model.side_effect = Exception("Bedrock down")
        fields, confidence, was_called = self.lf._extract_via_bedrock(
            "S", "B", [], "test-e03"
        )
        assert fields == {}
        assert confidence == pytest.approx(0.5)
        assert was_called is False
