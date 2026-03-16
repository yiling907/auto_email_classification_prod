#!/usr/bin/env python3
"""
InsureMail AI — Claude API Tool Calling with RBAC Permission Middleware
=======================================================================
Production-grade Claude API client with:
  - Role-based access control (readonly / developer / admin)
  - Tool call permission middleware (deny unauthorized tool use)
  - Structured audit logging (JSON lines to stdout + optional file)
  - Retry with exponential backoff on transient Bedrock/Anthropic errors
  - Clean dataclass interfaces for easy team adoption

Usage:
    from scripts.api.claude_tool_api import ClaudeToolClient, UserContext
    client = ClaudeToolClient()
    user   = UserContext(user_id="dev-01", role="developer", team="backend")
    result = client.run(user=user, prompt="Run the test suite and report results")

Roles:
    readonly   — read_file, list_files, search_code
    developer  — + write_file, run_tests, git_operations
    admin      — + deploy, manage_infrastructure, manage_secrets
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

# ── Logging ────────────────────────────────────────────────────────────────────

LOG_FILE = os.environ.get("CLAUDE_AUDIT_LOG", "")  # optional file sink

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",  # structured JSON lines — keep format clean
)
logger = logging.getLogger("claude_tool_api")

if LOG_FILE:
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.INFO)
    logger.addHandler(fh)


def _audit(event: str, **kwargs: Any) -> None:
    """Emit a structured audit log line."""
    record = {
        "ts":    datetime.now(timezone.utc).isoformat(),
        "event": event,
        **kwargs,
    }
    logger.info(json.dumps(record))


# ── Role definitions ───────────────────────────────────────────────────────────

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "readonly": {
        "read_file",
        "list_files",
        "search_code",
    },
    "developer": {
        "read_file",
        "list_files",
        "search_code",
        "write_file",
        "run_tests",
        "git_operations",
    },
    "admin": {
        "read_file",
        "list_files",
        "search_code",
        "write_file",
        "run_tests",
        "git_operations",
        "deploy",
        "manage_infrastructure",
        "manage_secrets",
    },
}

VALID_ROLES = set(ROLE_PERMISSIONS.keys())


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class UserContext:
    user_id: str
    role: str
    team: str = "default"

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{self.role}'. Must be one of: {sorted(VALID_ROLES)}")

    @property
    def allowed_tools(self) -> set[str]:
        return ROLE_PERMISSIONS[self.role]

    def can_use(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools


@dataclass
class ToolResult:
    tool_use_id: str
    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None


@dataclass
class RunResult:
    request_id: str
    user: UserContext
    prompt: str
    response_text: str
    tool_calls: list[dict] = field(default_factory=list)
    denied_calls: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float = 0.0
    success: bool = True
    error: str | None = None


# ── Tool definitions (sent to Claude) ─────────────────────────────────────────

ALL_TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file within the project directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path within the project"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a directory within the project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Relative directory path"},
                "pattern":   {"type": "string", "description": "Optional glob pattern (e.g. '*.py')"},
            },
            "required": ["directory"],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a pattern across project source files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":     {"type": "string", "description": "Search string or regex"},
                "file_glob": {"type": "string", "description": "Glob to restrict search (e.g. '**/*.py')"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file within the project directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "Relative file path"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_tests",
        "description": "Run the project test suite via pytest.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":   {"type": "string", "description": "Test path or module (default: tests/)"},
                "flags":  {"type": "string", "description": "Additional pytest flags (e.g. '-v -k test_rag')"},
            },
        },
    },
    {
        "name": "git_operations",
        "description": "Run safe git read operations (status, diff, log).",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["status", "diff", "log"],
                    "description": "Git operation to run",
                },
            },
            "required": ["operation"],
        },
    },
    {
        "name": "deploy",
        "description": "Build and deploy a project component (Lambda, dashboard, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component to deploy (e.g. 'dashboard', 'lambda/classify_intent')"},
                "environment": {"type": "string", "enum": ["dev", "staging", "prod"], "description": "Target environment"},
            },
            "required": ["component", "environment"],
        },
    },
    {
        "name": "manage_infrastructure",
        "description": "Run Terraform operations (plan / apply) on infrastructure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["plan", "apply"], "description": "Terraform operation"},
                "module":    {"type": "string", "description": "Optional Terraform module path"},
            },
            "required": ["operation"],
        },
    },
    {
        "name": "manage_secrets",
        "description": "Read or rotate secrets in AWS Secrets Manager.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action":     {"type": "string", "enum": ["get", "rotate"], "description": "Action to take"},
                "secret_name": {"type": "string", "description": "Secret name in Secrets Manager"},
            },
            "required": ["action", "secret_name"],
        },
    },
]


def _tools_for_role(role: str) -> list[dict]:
    """Return only tool definitions the role is permitted to use."""
    allowed = ROLE_PERMISSIONS[role]
    return [t for t in ALL_TOOLS if t["name"] in allowed]


# ── Tool executor ──────────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _execute_tool(tool_name: str, tool_input: dict, user: UserContext) -> ToolResult:
    """
    Execute a tool call. All paths are sandboxed to PROJECT_ROOT.
    Destructive tools (deploy, manage_infrastructure, manage_secrets) are stubbed
    and require additional confirmation in production.
    """
    tid = str(uuid.uuid4())[:8]

    try:
        if tool_name == "read_file":
            path = _safe_path(tool_input["path"])
            with open(path) as f:
                content = f.read()
            return ToolResult(tid, tool_name, True, output=content[:8000])

        elif tool_name == "list_files":
            import glob as _glob
            base = _safe_path(tool_input["directory"])
            pattern = tool_input.get("pattern", "*")
            files = _glob.glob(os.path.join(base, "**", pattern), recursive=True)
            return ToolResult(tid, tool_name, True, output=files[:200])

        elif tool_name == "search_code":
            import subprocess
            query     = tool_input["query"]
            file_glob = tool_input.get("file_glob", "**/*.py")
            result    = subprocess.run(
                ["grep", "-r", "--include", file_glob.replace("**/", ""), "-n", query, "."],
                capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=15,
            )
            return ToolResult(tid, tool_name, True, output=result.stdout[:4000])

        elif tool_name == "write_file":
            path    = _safe_path(tool_input["path"])
            content = tool_input["content"]
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return ToolResult(tid, tool_name, True, output=f"Written: {path}")

        elif tool_name == "run_tests":
            import subprocess
            path  = tool_input.get("path", "tests/")
            flags = tool_input.get("flags", "-v")
            cmd   = ["python", "-m", "pytest", path] + flags.split()
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=120)
            return ToolResult(tid, tool_name, result.returncode == 0,
                              output=result.stdout[-4000:] + result.stderr[-1000:])

        elif tool_name == "git_operations":
            import subprocess
            op_map = {"status": ["git", "status"], "diff": ["git", "diff"], "log": ["git", "log", "--oneline", "-20"]}
            cmd    = op_map[tool_input["operation"]]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=15)
            return ToolResult(tid, tool_name, True, output=result.stdout[:4000])

        elif tool_name in ("deploy", "manage_infrastructure", "manage_secrets"):
            # Stub — log the intent, return instructions for human execution
            return ToolResult(tid, tool_name, True,
                              output=f"[STUB] {tool_name} requested with {tool_input}. "
                                     f"Generate and review the appropriate script before executing manually.")

        else:
            return ToolResult(tid, tool_name, False, error=f"Unknown tool: {tool_name}")

    except Exception as e:
        return ToolResult(tid, tool_name, False, error=str(e))


def _safe_path(relative: str) -> str:
    """Resolve a relative path, ensuring it stays within PROJECT_ROOT."""
    resolved = os.path.realpath(os.path.join(PROJECT_ROOT, relative))
    if not resolved.startswith(PROJECT_ROOT):
        raise PermissionError(f"Path escape attempt blocked: {relative!r}")
    return resolved


# ── Claude API client ──────────────────────────────────────────────────────────

class ClaudeToolClient:
    """
    Production Claude API client with RBAC middleware.

    Uses Amazon Bedrock as the inference provider. Set AWS_REGION and
    appropriate IAM permissions before calling run().
    """

    MODEL_ID     = os.environ.get("CLAUDE_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
    MAX_TOKENS   = int(os.environ.get("CLAUDE_MAX_TOKENS", "4096"))
    MAX_RETRIES  = int(os.environ.get("CLAUDE_MAX_RETRIES", "3"))
    RETRY_DELAY  = float(os.environ.get("CLAUDE_RETRY_DELAY", "2.0"))  # seconds (doubles each retry)

    def __init__(self) -> None:
        self._bedrock = boto3.client("bedrock-runtime")

    def run(self, user: UserContext, prompt: str) -> RunResult:
        """
        Send a prompt to Claude with RBAC-filtered tools. Handles the full
        agentic loop (tool call → execute → tool result → continue).
        """
        request_id = str(uuid.uuid4())[:12]
        start_ms   = time.monotonic() * 1000

        _audit("request_start", request_id=request_id,
               user_id=user.user_id, role=user.role, team=user.team,
               prompt_preview=prompt[:120])

        result = RunResult(
            request_id=request_id,
            user=user,
            prompt=prompt,
            response_text="",
        )

        tools   = _tools_for_role(user.role)
        messages = [{"role": "user", "content": prompt}]

        try:
            # Agentic loop — continue until Claude stops requesting tools
            while True:
                response = self._invoke_with_retry(messages, tools)

                usage = response.get("usage", {})
                result.input_tokens  += usage.get("input_tokens", 0)
                result.output_tokens += usage.get("output_tokens", 0)

                stop_reason = response.get("stop_reason")
                content     = response.get("content", [])

                # Collect any text blocks
                for block in content:
                    if block.get("type") == "text":
                        result.response_text += block.get("text", "")

                if stop_reason != "tool_use":
                    break  # done

                # Process tool calls
                tool_results_content: list[dict] = []

                for block in content:
                    if block.get("type") != "tool_use":
                        continue

                    tool_name    = block["name"]
                    tool_use_id  = block["id"]
                    tool_input   = block.get("input", {})

                    # ── RBAC check ──────────────────────────────────────────
                    if not user.can_use(tool_name):
                        _audit("tool_denied", request_id=request_id,
                               user_id=user.user_id, role=user.role,
                               tool=tool_name)
                        result.denied_calls.append({"tool": tool_name, "input": tool_input})
                        tool_results_content.append({
                            "type":        "tool_result",
                            "tool_use_id": tool_use_id,
                            "content":     f"[DENIED] Your role '{user.role}' is not permitted to use '{tool_name}'.",
                            "is_error":    True,
                        })
                        continue

                    # ── Execute ─────────────────────────────────────────────
                    _audit("tool_call", request_id=request_id,
                           user_id=user.user_id, tool=tool_name, input_preview=str(tool_input)[:200])

                    tool_res = _execute_tool(tool_name, tool_input, user)

                    result.tool_calls.append({
                        "tool":    tool_name,
                        "input":   tool_input,
                        "success": tool_res.success,
                        "error":   tool_res.error,
                    })

                    _audit("tool_result", request_id=request_id,
                           tool=tool_name, success=tool_res.success, error=tool_res.error)

                    tool_results_content.append({
                        "type":        "tool_result",
                        "tool_use_id": tool_use_id,
                        "content":     json.dumps(tool_res.output) if tool_res.success else tool_res.error,
                        "is_error":    not tool_res.success,
                    })

                # Feed tool results back to Claude
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user",      "content": tool_results_content})

        except Exception as e:
            result.success = False
            result.error   = str(e)
            _audit("request_error", request_id=request_id, error=str(e))

        result.duration_ms = time.monotonic() * 1000 - start_ms

        _audit("request_complete", request_id=request_id,
               success=result.success, duration_ms=round(result.duration_ms, 1),
               input_tokens=result.input_tokens, output_tokens=result.output_tokens,
               tool_calls=len(result.tool_calls), denied_calls=len(result.denied_calls))

        return result

    def _invoke_with_retry(self, messages: list[dict], tools: list[dict]) -> dict:
        """Call Bedrock with exponential backoff on throttling / transient errors."""
        delay = self.RETRY_DELAY
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens":        self.MAX_TOKENS,
                    "tools":             tools,
                    "messages":          messages,
                })
                resp = self._bedrock.invoke_model(
                    modelId=self.MODEL_ID,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                return json.loads(resp["body"].read())

            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code in ("ThrottlingException", "ServiceUnavailableException") and attempt < self.MAX_RETRIES:
                    _audit("retry", attempt=attempt, error=code, delay_s=delay)
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="InsureMail AI Claude Tool API")
    parser.add_argument("--user-id",  default="cli-user",  help="User identifier")
    parser.add_argument("--role",     default="readonly",  choices=sorted(VALID_ROLES))
    parser.add_argument("--team",     default="default",   help="Team name")
    parser.add_argument("--prompt",   required=True,       help="Prompt to send to Claude")
    parser.add_argument("--log-file", default="",          help="Path to audit log file")
    args = parser.parse_args()

    if args.log_file:
        os.environ["CLAUDE_AUDIT_LOG"] = args.log_file

    client = ClaudeToolClient()
    user   = UserContext(user_id=args.user_id, role=args.role, team=args.team)
    result = client.run(user=user, prompt=args.prompt)

    print("\n" + "=" * 70)
    print(f"Request ID : {result.request_id}")
    print(f"User       : {result.user.user_id} ({result.user.role})")
    print(f"Duration   : {result.duration_ms:.0f} ms")
    print(f"Tokens     : {result.input_tokens} in / {result.output_tokens} out")
    print(f"Tool calls : {len(result.tool_calls)} executed, {len(result.denied_calls)} denied")
    print("=" * 70)
    print(result.response_text)

    sys.exit(0 if result.success else 1)
