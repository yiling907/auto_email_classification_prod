"""
reasoning_utils.py — Shared ReAct and Chain-of-Thought utilities for InsureMail AI.

All LLM-calling Lambdas import from here to avoid duplicating prompt scaffolds
and output parsers. Every parser implements a graceful fallback to brace-depth
JSON extraction so existing behaviour is never regressed when a model ignores
the sentinel format.
"""

import json
import re
from typing import Callable, Optional, Tuple

# ---------------------------------------------------------------------------
# Sentinel patterns (compiled once at module level)
# ---------------------------------------------------------------------------

# ReAct: model must end with  FINAL_ANSWER: {...}
_FINAL_ANSWER_RE = re.compile(r'FINAL_ANSWER:\s*(\{[\s\S]*\})', re.IGNORECASE)

# CoT: model must end with  FINAL_JSON: {...}
_FINAL_JSON_RE = re.compile(r'FINAL_JSON:\s*(\{[\s\S]*\})', re.IGNORECASE)

# CoT: reasoning wrapped in <reasoning>...</reasoning>
_REASONING_RE = re.compile(r'<reasoning>([\s\S]*?)</reasoning>', re.IGNORECASE)

# ---------------------------------------------------------------------------
# Prompt prefix constants
# ---------------------------------------------------------------------------

REACT_SYSTEM_PREFIX = (
    "You solve problems by interleaving Thought, Action, and Observation steps.\n"
    "- Thought: reason about what you know and what you need.\n"
    "- Action: state exactly one action to take (e.g. CLASSIFY, SELECT_FIELD, SCORE).\n"
    "- Observation: note what the action result tells you.\n"
    "Repeat as needed. End ONLY with:\n"
    "FINAL_ANSWER: <valid JSON, no markdown fences>\n"
)

COT_SYSTEM_PREFIX = (
    "Before producing your final JSON, write a step-by-step analysis "
    "inside <reasoning>...</reasoning> tags.\n"
    "After the closing </reasoning> tag, output:\n"
    "FINAL_JSON: <valid JSON, no markdown fences>\n"
)

# ---------------------------------------------------------------------------
# Mistral format wrapper
# ---------------------------------------------------------------------------

def wrap_mistral(instruction: str) -> str:
    """Wrap a prompt in Mistral's <s>[INST]...[/INST] instruction format."""
    return f"<s>[INST] {instruction} [/INST]"


# ---------------------------------------------------------------------------
# JSON block extractor (fallback)
# ---------------------------------------------------------------------------

def extract_json_block(text: str) -> str:
    """
    Extract the first complete {...} block from *text* using brace-depth tracking.

    This is the fallback parser used when a model ignores the sentinel format.
    Returns an empty string if no complete JSON object is found.
    """
    start = text.find('{')
    if start == -1:
        return ''
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ''


# ---------------------------------------------------------------------------
# ReAct parser
# ---------------------------------------------------------------------------

def extract_react_answer(raw: str) -> Tuple[str, str]:
    """
    Parse a ReAct-formatted model output that ends with a FINAL_ANSWER: block.

    Returns:
        (scratchpad, final_answer_json_str)

    *scratchpad* is everything before the last FINAL_ANSWER: sentinel.
    *final_answer_json_str* is the JSON string extracted from the sentinel.

    If the sentinel is absent the function falls back to extract_json_block()
    and returns ('', json_str_or_empty).
    """
    # Find the last occurrence of the sentinel (case-insensitive)
    sentinel = 'FINAL_ANSWER:'
    upper_raw = raw.upper()
    idx = upper_raw.rfind(sentinel.upper())
    if idx != -1:
        scratchpad = raw[:idx].strip()
        after_sentinel = raw[idx + len(sentinel):].strip()
        json_str = extract_json_block(after_sentinel)
        return scratchpad, json_str

    # Fallback: no sentinel found
    json_str = extract_json_block(raw)
    return '', json_str


# ---------------------------------------------------------------------------
# CoT parser
# ---------------------------------------------------------------------------

def extract_cot_answer(raw: str) -> Tuple[str, str]:
    """
    Parse a CoT-formatted model output that ends with a FINAL_JSON: block.

    Returns:
        (reasoning_text, json_str)

    *reasoning_text* is the content of the <reasoning>...</reasoning> block
    (or an empty string when the tags are absent).
    *json_str* is the JSON string extracted from the FINAL_JSON: sentinel.

    If the FINAL_JSON: sentinel is absent the function falls back to
    extract_json_block().
    """
    # Extract <reasoning> block (optional)
    reasoning_match = _REASONING_RE.search(raw)
    reasoning_text = reasoning_match.group(1).strip() if reasoning_match else ''

    # Extract FINAL_JSON sentinel (prefer last occurrence)
    sentinel = 'FINAL_JSON:'
    upper_raw = raw.upper()
    idx = upper_raw.rfind(sentinel.upper())
    if idx != -1:
        after_sentinel = raw[idx + len(sentinel):].strip()
        json_str = extract_json_block(after_sentinel)
        return reasoning_text, json_str

    # Fallback
    json_str = extract_json_block(raw)
    return reasoning_text, json_str


# ---------------------------------------------------------------------------
# Reasoning trace logger
# ---------------------------------------------------------------------------

def log_reasoning_trace(
    logger_fn: Callable,
    email_id: str,
    lambda_name: str,
    scratchpad: str,
    final_answer: str,
    reasoning_format_valid: bool = True,
) -> None:
    """
    Emit a structured JSON log line containing the reasoning trace.

    *logger_fn* should be ``logger.info`` or ``print`` depending on what the
    calling Lambda uses.  The scratchpad is truncated to 2000 chars to avoid
    CloudWatch bloat while keeping the full final answer.

    Log shape::

        {
          "trace_id": "<email_id>",
          "lambda":   "<lambda_name>",
          "reasoning_chain": "<scratchpad[:2000]>",
          "final_answer": "<final_answer>",
          "reasoning_format_valid": true|false
        }
    """
    record = {
        "trace_id": email_id,
        "lambda": lambda_name,
        "reasoning_chain": scratchpad[:2000] if scratchpad else '',
        "final_answer": final_answer,
        "reasoning_format_valid": reasoning_format_valid,
    }
    logger_fn(json.dumps(record))


# ---------------------------------------------------------------------------
# Convenience: parse JSON safely
# ---------------------------------------------------------------------------

def safe_json_loads(json_str: str) -> Optional[dict]:
    """
    Attempt to JSON-parse *json_str*.  Returns None on failure instead of
    raising, so callers can handle the fallback gracefully.
    """
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None
