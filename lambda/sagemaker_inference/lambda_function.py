"""
sagemaker_inference Lambda — API Gateway handler that calls the SageMaker endpoint.

Triggered by: POST /api/model/inference  (via API Gateway)
Request body: {"instances": [[float, ...], ...]}
Response:     {"predictions": [[float, ...], ...]}

Environment variables:
  SAGEMAKER_ENDPOINT_NAME  — name of the deployed SageMaker endpoint
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "")
CONTENT_TYPE = "application/json"

# CORS headers returned on every response
CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}

# Reuse the boto3 client across warm Lambda invocations
sagemaker_runtime = boto3.client("sagemaker-runtime")


def lambda_handler(event, context):
    """
    1. Parse the request body from API Gateway event.
    2. Forward it to the SageMaker endpoint.
    3. Return the prediction as a JSON HTTP response.
    """
    # ── Handle CORS preflight ─────────────────────────────────────────────────
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # ── Parse request body ────────────────────────────────────────────────────
    # Accepts: {"instances": ["text1", "text2"]}  or  {"text": "single text"}
    try:
        raw_body = event.get("body") or "{}"
        body = json.loads(raw_body)

        if "instances" in body:
            instances = body["instances"]
        elif "text" in body:
            instances = [body["text"]] if isinstance(body["text"], str) else body["text"]
        else:
            return _error(400, "Request body must contain 'instances' (list of strings) or 'text' (string).")

        if not isinstance(instances, list) or not instances:
            return _error(400, "'instances' must be a non-empty list of strings.")

    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Bad request body: %s", exc)
        return _error(400, f"Invalid JSON body: {exc}")

    # ── Invoke SageMaker endpoint ─────────────────────────────────────────────
    payload = json.dumps({"instances": instances})
    logger.info(
        "Invoking endpoint=%s  payload_size=%d bytes",
        ENDPOINT_NAME, len(payload),
    )

    try:
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=ENDPOINT_NAME,
            ContentType=CONTENT_TYPE,
            Accept=CONTENT_TYPE,
            Body=payload.encode("utf-8"),
        )
        result = json.loads(response["Body"].read().decode("utf-8"))

    except sagemaker_runtime.exceptions.ModelNotReadyException:
        logger.error("Endpoint '%s' is not ready.", ENDPOINT_NAME)
        return _error(503, f"SageMaker endpoint '{ENDPOINT_NAME}' is not ready yet. Retry in a few minutes.")

    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        msg = exc.response["Error"]["Message"]
        logger.error("SageMaker ClientError %s: %s", code, msg)
        return _error(502, f"Inference failed: {msg}")

    except Exception as exc:
        logger.exception("Unexpected error calling SageMaker endpoint")
        return _error(500, f"Internal error: {str(exc)}")

    # ── Return prediction ─────────────────────────────────────────────────────
    # HuggingFace DLC serialises output_fn's (body, content_type) tuple as a JSON list.
    # Unwrap: [json_string, "application/json"] → parse the inner JSON.
    if isinstance(result, list) and len(result) == 2 and isinstance(result[0], str):
        result = json.loads(result[0])
    predictions = result.get("predictions", result) if isinstance(result, dict) else result
    logger.info("Inference success: predictions_count=%d", len(predictions))
    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps({"predictions": predictions}),
    }


def _error(status_code: int, message: str) -> dict:
    """Build a standard error response."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps({"error": message}),
    }
