"""
save_result Lambda — final step in the InsureMail AI pipeline.

Saves the complete Step Functions input to the pipeline_results DynamoDB table.
Three structured keys (email_id, final_action, executed_at) support PK/GSI queries;
the full execution state is stored as a JSON string in `input` for audit and analytics.

Never raises — any exception is caught so the workflow always reaches Success.
"""
import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("PIPELINE_RESULTS_TABLE_NAME", "")
dynamodb = boto3.resource("dynamodb")


def lambda_handler(event, context):
    try:
        # ── PK: email_id ─────────────────────────────────────────────────────
        parsed_email = event.get("parsed_email") or {}
        email_id = parsed_email.get("email_id", "unknown")

        # ── GSI PK: final_action ─────────────────────────────────────────────
        # AutoRespond success  → $.email_result.email_sent = True
        # AutoRespond Catch    → $.email_error set; no final_action
        # Pass states          → $.final_action.action
        email_result = event.get("email_result") or {}
        final_action_obj = event.get("final_action") or {}

        if email_result.get("email_sent"):
            final_action = "auto_response"
        elif final_action_obj:
            final_action = final_action_obj.get("action", "unknown")
        else:
            final_action = "auto_response"  # AutoRespond Catch path

        # ── GSI SK: executed_at ───────────────────────────────────────────────
        executed_at = datetime.now(timezone.utc).isoformat()

        # ── full input stored as JSON string ──────────────────────────────────
        input_json = json.dumps(event, default=str)

        item = {
            "email_id": email_id,
            "final_action": final_action,
            "executed_at": executed_at,
            "input": input_json,
            "pipeline_version": "1.0",
        }

        dynamodb.Table(TABLE_NAME).put_item(Item=item)

        logger.info(
            "Saved pipeline result: email_id=%s final_action=%s input_size=%d bytes",
            email_id, final_action, len(input_json),
        )
        return {"saved": True, "email_id": email_id, "final_action": final_action}

    except Exception as exc:
        logger.error("save_result failed (non-fatal): %s", exc, exc_info=True)
        return {"saved": False, "error": str(exc)}
