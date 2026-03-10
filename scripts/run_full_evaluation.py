#!/usr/bin/env python3
"""
Full evaluation orchestrator for InsureMail AI.

Runs the complete evaluation pipeline in sequence:
  1. Generate laya eval datasets (and upload to S3)
  2. Run local evaluation (intent/routing/calibration + entity extraction)
  3. Submit Bedrock evaluation jobs (laya datasets, LLM-as-judge)

Usage:
  python scripts/run_full_evaluation.py [--n-emails N] [--n-attachments N]
                                         [--dry-run] [--skip-upload] [--skip-bedrock]
                                         [--bucket S3_BUCKET]
                                         [--lambda-function BEDROCK_EVAL_FUNCTION]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def run_step(description: str, cmd: list[str]) -> int:
    """Run a subprocess step, print output, return exit code."""
    print(f"\n{'='*60}")
    print(f"STEP: {description}")
    print(f"  cmd: {' '.join(cmd)}")
    print("="*60)
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"\n[ERROR] Step failed with exit code {result.returncode}: {description}")
    return result.returncode


def submit_bedrock_jobs(
    lambda_function: str,
    dataset_source: str = "laya",
) -> None:
    """Invoke the bedrock_evaluation Lambda to submit evaluation jobs."""
    import boto3
    print(f"\n{'='*60}")
    print("STEP: Submit Bedrock evaluation jobs")
    print(f"  Lambda: {lambda_function}")
    print(f"  dataset_source: {dataset_source}")
    print("="*60)

    client = boto3.client("lambda")
    payload = {"action": "submit", "dataset_source": dataset_source}
    try:
        response = client.invoke(
            FunctionName=lambda_function,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )
        resp_payload = json.loads(response["Payload"].read())
        jobs_submitted = resp_payload.get("jobs_submitted", 0)
        print(f"  Bedrock eval jobs submitted: {jobs_submitted}")
        for job in resp_payload.get("jobs", []):
            status = "OK" if "job_arn" in job else "ERROR"
            print(f"    [{status}] {job.get('model_name','?')} — {job.get('job_arn', job.get('error',''))}")
    except Exception as exc:
        print(f"  [ERROR] Failed to invoke Lambda: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full InsureMail evaluation pipeline")
    parser.add_argument("--n-emails",      type=int, default=50)
    parser.add_argument("--n-attachments", type=int, default=30)
    parser.add_argument("--seed",          type=int, default=42)
    parser.add_argument("--dry-run",  action="store_true",
                        help="Mock Bedrock calls (no real inference)")
    parser.add_argument("--skip-upload", action="store_true",
                        help="Skip S3 upload in dataset generation step")
    parser.add_argument("--skip-bedrock", action="store_true",
                        help="Skip submitting Bedrock eval jobs")
    parser.add_argument("--bucket", default=None,
                        help="S3 bucket override (else KNOWLEDGE_BASE_BUCKET env var)")
    parser.add_argument("--lambda-function", default=None,
                        help="Bedrock evaluation Lambda function name")
    args = parser.parse_args()

    start_ts = datetime.now(timezone.utc).isoformat()
    print(f"\nInsureMail Full Evaluation Pipeline — {start_ts}")

    # ------------------------------------------------------------------
    # Step 1: Generate eval datasets
    # ------------------------------------------------------------------
    gen_cmd = [sys.executable, str(SCRIPTS_DIR / "generate_eval_datasets.py")]
    if not args.skip_upload and not args.dry_run:
        gen_cmd.append("--upload")
    if args.bucket:
        gen_cmd += ["--bucket", args.bucket]
    gen_cmd += ["--seed", str(args.seed)]

    rc = run_step("Generate laya evaluation datasets", gen_cmd)
    if rc != 0:
        print("[WARN] Dataset generation failed — continuing with existing files if present.")

    # ------------------------------------------------------------------
    # Step 2: Local evaluation
    # ------------------------------------------------------------------
    local_cmd = [
        sys.executable, str(SCRIPTS_DIR / "run_local_evaluation.py"),
        "--n-emails",      str(args.n_emails),
        "--n-attachments", str(args.n_attachments),
        "--seed",          str(args.seed),
    ]
    if args.dry_run:
        local_cmd.append("--dry-run")

    rc = run_step("Local evaluation (intent + routing + entity extraction)", local_cmd)
    if rc != 0:
        print("[WARN] Local evaluation step failed.")

    # ------------------------------------------------------------------
    # Step 3: Submit Bedrock evaluation jobs
    # ------------------------------------------------------------------
    if args.skip_bedrock:
        print("\n[SKIP] Bedrock eval job submission skipped (--skip-bedrock).")
    elif args.dry_run:
        print("\n[SKIP] Bedrock eval job submission skipped in dry-run mode.")
    else:
        fn_name = args.lambda_function or os.environ.get(
            "BEDROCK_EVAL_FUNCTION_NAME", "insuremail-bedrock-evaluation"
        )
        submit_bedrock_jobs(lambda_function=fn_name, dataset_source="laya")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    end_ts = datetime.now(timezone.utc).isoformat()
    print(f"\n{'='*60}")
    print(f"Full evaluation pipeline complete.")
    print(f"Started:  {start_ts}")
    print(f"Finished: {end_ts}")
    print(f"Results:  {REPO_ROOT / 'results'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
