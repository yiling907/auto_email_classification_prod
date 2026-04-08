"""
tests/unit/test_reasoning_utils.py

Unit tests for lambda/shared/reasoning_utils.py.
Run with:
    EMAIL_TABLE_NAME=test-emails pytest tests/unit/test_reasoning_utils.py -v
"""

import json
import sys
import os
import pytest

# Make the shared module importable without a package install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/shared'))

from reasoning_utils import (
    extract_react_answer,
    extract_cot_answer,
    extract_json_block,
    log_reasoning_trace,
    wrap_mistral,
    safe_json_loads,
    REACT_SYSTEM_PREFIX,
    COT_SYSTEM_PREFIX,
)


# ---------------------------------------------------------------------------
# wrap_mistral
# ---------------------------------------------------------------------------

class TestWrapMistral:
    def test_wraps_with_inst_tags(self):
        result = wrap_mistral("Hello")
        assert result == "<s>[INST] Hello [/INST]"

    def test_preserves_multiline_instruction(self):
        instruction = "Line 1\nLine 2"
        result = wrap_mistral(instruction)
        assert "[INST] Line 1\nLine 2 [/INST]" in result


# ---------------------------------------------------------------------------
# extract_json_block
# ---------------------------------------------------------------------------

class TestExtractJsonBlock:
    def test_simple_flat_object(self):
        text = 'Preamble {"key": "value"} trailing'
        assert extract_json_block(text) == '{"key": "value"}'

    def test_nested_object(self):
        text = '{"outer": {"inner": 1}}'
        result = extract_json_block(text)
        assert json.loads(result) == {"outer": {"inner": 1}}

    def test_picks_first_complete_object(self):
        text = 'prefix {"a": 1} {"b": 2}'
        assert extract_json_block(text) == '{"a": 1}'

    def test_empty_input_returns_empty_string(self):
        assert extract_json_block('') == ''

    def test_no_json_returns_empty_string(self):
        assert extract_json_block('no json here') == ''

    def test_markdown_fenced_json(self):
        text = '```json\n{"x": 42}\n```'
        result = extract_json_block(text)
        assert json.loads(result) == {"x": 42}

    def test_escaped_braces_in_string_not_counted(self):
        text = '{"msg": "open { close }"}'
        result = extract_json_block(text)
        assert json.loads(result) == {"msg": "open { close }"}

    def test_deeply_nested(self):
        text = '{"a": {"b": {"c": {"d": 1}}}}'
        result = extract_json_block(text)
        assert json.loads(result)["a"]["b"]["c"]["d"] == 1


# ---------------------------------------------------------------------------
# extract_react_answer
# ---------------------------------------------------------------------------

class TestExtractReactAnswer:
    def test_sentinel_present_returns_scratchpad_and_json(self):
        raw = (
            "Thought 1: The email is about a claim.\n"
            "Action 1: CLASSIFY\n"
            "Observation 1: Intent is claim_submission.\n"
            'FINAL_ANSWER: {"customer_intent": "claim_submission"}'
        )
        scratchpad, json_str = extract_react_answer(raw)
        assert "Thought 1" in scratchpad
        assert json.loads(json_str) == {"customer_intent": "claim_submission"}

    def test_sentinel_absent_returns_empty_scratchpad_and_json(self):
        raw = 'Some text {"customer_intent": "claim_status"} more text'
        scratchpad, json_str = extract_react_answer(raw)
        assert scratchpad == ''
        assert json.loads(json_str) == {"customer_intent": "claim_status"}

    def test_multiple_sentinels_picks_last(self):
        raw = (
            'FINAL_ANSWER: {"step": 1}\n'
            'FINAL_ANSWER: {"step": 2}\n'
        )
        _, json_str = extract_react_answer(raw)
        assert json.loads(json_str)["step"] == 2

    def test_case_insensitive_sentinel(self):
        raw = 'final_answer: {"score": 9}'
        _, json_str = extract_react_answer(raw)
        assert json.loads(json_str)["score"] == 9

    def test_no_json_anywhere_returns_empty_strings(self):
        raw = "Thought 1: No idea what to do."
        scratchpad, json_str = extract_react_answer(raw)
        assert scratchpad == ''
        assert json_str == ''

    def test_sentinel_with_nested_json(self):
        raw = 'FINAL_ANSWER: {"a": {"b": 2}}'
        _, json_str = extract_react_answer(raw)
        assert json.loads(json_str) == {"a": {"b": 2}}

    def test_scratchpad_stripped_of_whitespace(self):
        raw = '   Thought 1: hello   \nFINAL_ANSWER: {"x": 1}'
        scratchpad, _ = extract_react_answer(raw)
        assert scratchpad == 'Thought 1: hello'


# ---------------------------------------------------------------------------
# extract_cot_answer
# ---------------------------------------------------------------------------

class TestExtractCotAnswer:
    def test_reasoning_tags_and_final_json_extracted(self):
        raw = (
            "<reasoning>\nStep 1: Member details found.\n</reasoning>\n"
            'FINAL_JSON: {"membership_no": "LH12345"}'
        )
        reasoning, json_str = extract_cot_answer(raw)
        assert "Step 1" in reasoning
        assert json.loads(json_str)["membership_no"] == "LH12345"

    def test_missing_reasoning_tags_returns_empty_reasoning(self):
        raw = 'FINAL_JSON: {"confidence": 0.8}'
        reasoning, json_str = extract_cot_answer(raw)
        assert reasoning == ''
        assert json.loads(json_str)["confidence"] == 0.8

    def test_sentinel_absent_falls_back_to_json_block(self):
        raw = 'Some analysis {"field": "value"}'
        reasoning, json_str = extract_cot_answer(raw)
        assert json.loads(json_str)["field"] == "value"

    def test_multiple_final_json_picks_last(self):
        raw = (
            'FINAL_JSON: {"v": 1}\n'
            'FINAL_JSON: {"v": 2}\n'
        )
        _, json_str = extract_cot_answer(raw)
        assert json.loads(json_str)["v"] == 2

    def test_case_insensitive_reasoning_tags(self):
        raw = '<REASONING>Step 1.</REASONING>FINAL_JSON: {"ok": true}'
        reasoning, json_str = extract_cot_answer(raw)
        assert "Step 1" in reasoning
        assert json.loads(json_str)["ok"] is True

    def test_no_json_returns_empty_json_str(self):
        raw = '<reasoning>Thinking...</reasoning>No JSON here.'
        reasoning, json_str = extract_cot_answer(raw)
        assert "Thinking" in reasoning
        assert json_str == ''


# ---------------------------------------------------------------------------
# log_reasoning_trace
# ---------------------------------------------------------------------------

class TestLogReasoningTrace:
    def _capture_log(self):
        """Returns a log function and a list that collects its output."""
        lines = []
        return lines.append, lines

    def test_emits_structured_json(self):
        log_fn, lines = self._capture_log()
        log_reasoning_trace(log_fn, "email-1", "classify_intent", "Thought 1", '{"x":1}')
        record = json.loads(lines[0])
        assert record["trace_id"] == "email-1"
        assert record["lambda"] == "classify_intent"
        assert record["reasoning_chain"] == "Thought 1"
        assert record["final_answer"] == '{"x":1}'
        assert record["reasoning_format_valid"] is True

    def test_long_scratchpad_truncated_at_2000(self):
        long_scratchpad = "x" * 3000
        log_fn, lines = self._capture_log()
        log_reasoning_trace(log_fn, "e", "lmb", long_scratchpad, "{}")
        record = json.loads(lines[0])
        assert len(record["reasoning_chain"]) == 2000

    def test_empty_scratchpad_stored_as_empty_string(self):
        log_fn, lines = self._capture_log()
        log_reasoning_trace(log_fn, "e", "lmb", '', '{}')
        record = json.loads(lines[0])
        assert record["reasoning_chain"] == ''

    def test_reasoning_format_valid_false_stored(self):
        log_fn, lines = self._capture_log()
        log_reasoning_trace(log_fn, "e", "lmb", '', '{}', reasoning_format_valid=False)
        record = json.loads(lines[0])
        assert record["reasoning_format_valid"] is False

    def test_output_is_valid_json(self):
        log_fn, lines = self._capture_log()
        log_reasoning_trace(log_fn, "e", "lmb", "some reasoning", '{"score": 9}')
        json.loads(lines[0])  # should not raise


# ---------------------------------------------------------------------------
# safe_json_loads
# ---------------------------------------------------------------------------

class TestSafeJsonLoads:
    def test_valid_json_returns_dict(self):
        result = safe_json_loads('{"a": 1}')
        assert result == {"a": 1}

    def test_invalid_json_returns_none(self):
        assert safe_json_loads('not json') is None

    def test_empty_string_returns_none(self):
        assert safe_json_loads('') is None

    def test_none_input_returns_none(self):
        assert safe_json_loads(None) is None


# ---------------------------------------------------------------------------
# Prompt prefix constants (smoke tests)
# ---------------------------------------------------------------------------

class TestPromptConstants:
    def test_react_prefix_contains_key_terms(self):
        assert "Thought" in REACT_SYSTEM_PREFIX
        assert "Action" in REACT_SYSTEM_PREFIX
        assert "FINAL_ANSWER" in REACT_SYSTEM_PREFIX

    def test_cot_prefix_contains_key_terms(self):
        assert "<reasoning>" in COT_SYSTEM_PREFIX
        assert "FINAL_JSON" in COT_SYSTEM_PREFIX
