#!/usr/bin/env python3
"""
InsureMail AI — Local Development API Server
=============================================
Serves dashboard API endpoints on http://localhost:3001 using local data files.
Replaces the deployed AWS API Gateway + Lambda during local development.

Usage
-----
    python scripts/dev_server.py            # start server (port 3001)
    python scripts/dev_server.py --port 3001

Endpoints served
----------------
  GET  /api/dashboard/overview      mock overview stats
  GET  /api/emails                  mock emails list
  GET  /api/metrics/models          mock model metrics
  GET  /api/metrics/rag             mock RAG metrics
  GET  /api/metrics/evaluations     mock evaluations (+ reference eval report)
  GET  /api/settings                mock settings
  GET  /api/assessment              latest e2e assessment from results/
  POST /api/assessment/run          run scripts/run_e2e_assessment.py
  OPTIONS *                         CORS preflight
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
REFERENCE_EVAL = RESULTS_DIR / "reference_eval_report.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Content-Type": "application/json",
}


def _latest_assessment() -> dict | None:
    """Return the most-recently modified assessment JSON from results/."""
    pattern = str(RESULTS_DIR / "e2e_assessment*.json")
    files = sorted(_glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not files:
        return None
    with open(files[0], encoding="utf-8") as fh:
        return json.load(fh)


def _reference_eval() -> dict:
    if REFERENCE_EVAL.exists():
        with open(REFERENCE_EVAL, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


# ── Mock data ─────────────────────────────────────────────────────────────────

def mock_overview() -> dict:
    assessment = _latest_assessment()
    n = assessment["assessment_metadata"]["n_emails"] if assessment else 0
    composite = assessment["composite_score"] if assessment else 0.0
    dims = assessment.get("dimensions", {}) if assessment else {}
    auto_pct = dims.get("confidence_calibration", {}).get("routing_distribution", {}).get("auto_response", 0.66)
    return {
        "total_emails": n,
        "avg_confidence": round(composite, 2),
        "auto_response_rate": round(auto_pct * 100, 1),
        "confidence_distribution": {"high": int(n * auto_pct), "medium": int(n * 0.34), "low": 0, "pending": 0},
        "recent_emails": [],
    }


def mock_evaluations() -> dict:
    ref = _reference_eval()
    return {"reference_eval": ref, "bedrock_evals": [], "claude_evals": []}


# ── Assessment runner (async) ─────────────────────────────────────────────────

_run_lock = threading.Lock()
_run_status = {"running": False, "last_exit": None, "last_started": None}


def _do_run():
    import datetime
    with _run_lock:
        _run_status["running"] = True
        _run_status["last_started"] = datetime.datetime.utcnow().isoformat() + "Z"
    cmd = [sys.executable, str(ROOT / "scripts" / "run_stepfn_assessment.py"), "--sample", "20"]
    result = subprocess.run(cmd, cwd=str(ROOT))
    with _run_lock:
        _run_status["running"] = False
        _run_status["last_exit"] = result.returncode


# ── Request handler ───────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet console
        print(f"  {self.command} {self.path}  →  {args[1] if len(args) > 1 else ''}")

    def _send(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "/api/dashboard/overview":
            self._send(200, mock_overview())

        elif path == "/api/emails":
            self._send(200, {"emails": [], "count": 0})

        elif path == "/api/metrics/models":
            self._send(200, {"total_records": 0, "by_task": {}, "by_model": {}, "records": []})

        elif path == "/api/metrics/rag":
            self._send(200, {"total_chunks": 0, "total_source_files": 0, "chunks_per_file": {}, "status": "empty"})

        elif path == "/api/metrics/evaluations":
            self._send(200, mock_evaluations())

        elif path == "/api/settings":
            self._send(200, {"settings": {"classify_intent": "mistral-7b", "claude_response": "mistral-7b"}, "valid_models": ["llama-3.1-8b", "mistral-7b"]})

        elif path == "/api/assessment":
            report = _latest_assessment()
            if report is None:
                self._send(404, {"error": "No assessment report found. Run python scripts/run_e2e_assessment.py --dry-run"})
            else:
                self._send(200, report)

        else:
            self._send(404, {"error": f"Not found: {path}"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "/api/assessment/run":
            with _run_lock:
                if _run_status["running"]:
                    self._send(409, {"status": "already_running", "started": _run_status["last_started"]})
                    return
            thread = threading.Thread(target=_do_run, daemon=True)
            thread.start()
            self._send(202, {"status": "triggered",
                             "message": "Live pipeline assessment triggered (sample=20). Refresh in ~3min."})

        elif path == "/api/settings":
            self._send(200, {"updated": {}})

        else:
            self._send(404, {"error": f"Not found: {path}"})


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="InsureMail AI local dev server")
    parser.add_argument("--port", type=int, default=3001)
    args = parser.parse_args()

    server = HTTPServer(("localhost", args.port), Handler)
    print(f"InsureMail AI dev server listening on http://localhost:{args.port}")
    print(f"Results dir : {RESULTS_DIR}")
    assessment = _latest_assessment()
    if assessment:
        print(f"Assessment  : found ({assessment['assessment_metadata'].get('n_emails')} emails, "
              f"score={assessment['composite_score']:.4f})")
    else:
        print("Assessment  : not found — run: python scripts/run_e2e_assessment.py --dry-run")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
