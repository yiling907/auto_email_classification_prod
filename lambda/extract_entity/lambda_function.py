"""
Extract Entity Lambda
=====================
Production entity extraction using Amazon Textract + AWS Bedrock Claude.

Flow:
  1. Seed base entities (policy_number, member_id, customer_id, sender_email,
     pii_present) from email_parser output passed via Step Functions.
  2. Collect pre-extracted attachment text already produced by email_parser
     (PDF/DOCX/TXT content stored in attachments_content list).
  3. For attachments that email_parser could not parse (PNG/JPG/scanned docs),
     fetch the raw MIME email from S3, extract attachment bytes, and run
     Amazon Textract DetectDocumentText.
  4. Call Bedrock Claude 3 Haiku with the full text corpus (email body +
     attachment text) to extract structured insurance domain fields.
  5. Return a standardised entity JSON stored at $.entities in the Step
     Functions state.

Environment variables:
    ENTITY_MODEL_ID   — Bedrock model for structured extraction
                        (default: anthropic.claude-3-haiku-20240307-v1:0)
    AWS_REGION        — AWS region (default: us-east-1)

Input event keys (passed from Step Functions Parameters block):
    email_id              (str)  — trace ID
    email_body            (str)  — full plain-text email body
    subject               (str)  — email subject line
    sender_email          (str)  — sender address
    policy_number         (str, optional) — pre-extracted by email_parser
    member_id             (str, optional) — pre-extracted by email_parser
    customer_id           (str, optional) — pre-extracted by email_parser
    pii_present           (bool) — PII detected flag from email_parser
    has_attachment        (bool) — True when email has ≥1 attachment
    attachments_content   (list) — pre-extracted attachment text entries
    s3_bucket             (str)  — S3 bucket holding the raw email
    s3_key                (str)  — S3 key of the raw MIME email

Output (stored at ResultPath $.entities):
    policy_number         (str | None)  — from email_parser / Bedrock
    member_id             (str | None)
    customer_id           (str | None)
    sender_email          (str)
    pii_present           (bool)
    extracted_fields      (dict)  — Laya Out-patient Claim Form fields:
        membership_no, title, surname, forenames, date_of_birth,
        telephone, correspondence_address,
        dependants[]        (name, relationship),
        mri_date, mri_reason_for_referral, mri_centre, mri_procedure,
        mri_referring_gp, mri_consultant_code,
        accident_date, accident_description, expenses_recoverable,
        recovery_via_solicitor, recovery_via_piab, third_party_details,
        dental_injury_date, dental_injury_place, dental_injury_description,
        dental_treatment_start, dental_treatment_end, dental_cost,
        receipts[]          (treatment_type, num_receipts, total_cost),
        receipts_total_cost,
        account_holder_name, account_number, bank_sort_code,
        bank_name_address, declaration_date, doc_category
    textract_used         (bool)
    bedrock_used          (bool)
    extraction_confidence (float 0–1)
    sources               (list[str])
"""

import email as _email_lib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# ── Logging ───────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── AWS clients (initialised once at cold start) ──────────────────────────────

_REGION  = os.environ.get("AWS_REGION", "us-east-1")
bedrock  = boto3.client("bedrock-runtime", region_name=_REGION)
textract = boto3.client("textract",         region_name=_REGION)
s3       = boto3.client("s3",               region_name=_REGION)

# ── Environment ───────────────────────────────────────────────────────────────

ENTITY_MODEL_ID = os.environ.get(
    "ENTITY_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
)

# ── MIME content types that require Textract (image-based) ────────────────────

_IMAGE_EXTENSIONS   = frozenset({"jpg", "jpeg", "png", "tiff", "tif"})
_IMAGE_CONTENT_TYPES = frozenset({
    "image/jpeg", "image/jpg", "image/png", "image/tiff",
})
_PDF_CONTENT_TYPES  = frozenset({"application/pdf"})

# ── Bedrock structured extraction prompt ──────────────────────────────────────
# Schema mirrors the Laya Healthcare Out-patient Claim Form (sections 1–8).

_EXTRACTION_PROMPT = """\
You are an insurance document entity extractor specialised in Laya Healthcare \
Out-patient Claim Forms (Ireland).

Given text from a Laya Healthcare email and/or an attached Out-patient Claim \
Form, extract every field listed below. Use null for any field not present in \
the source text. Return ONLY valid JSON — no explanation, no markdown.

--- SECTION 1: Member's details ---
  membership_no          : string  (laya membership number)
  title                  : string  (Mr / Ms / Mrs / Dr / Prof etc.)
  surname                : string
  forenames              : string
  date_of_birth          : string  ISO date YYYY-MM-DD or null
  telephone              : string
  correspondence_address : string  (full address, newlines replaced with ", ")

--- SECTION 2: Dependants ---
  dependants             : array of objects, each:
    {{ "name": string, "relationship": string }}
  (empty array [] if none)

--- SECTION 3: MRI ---
  mri_date               : string  ISO date YYYY-MM-DD or null
  mri_reason_for_referral: string or null
  mri_centre             : string or null
  mri_procedure          : string  (names and codes) or null
  mri_referring_gp       : string  (GP or consultant name) or null
  mri_consultant_code    : string or null

--- SECTION 4: Accidents ---
  accident_date          : string  ISO date YYYY-MM-DD or null
  accident_description   : string or null
  expenses_recoverable   : boolean or null
  recovery_via_solicitor : boolean or null
  recovery_via_piab      : boolean or null  (Personal Injuries Assessment Board)
  third_party_details    : string or null

--- SECTION 5: Emergency Dental ---
  dental_injury_date     : string  ISO date YYYY-MM-DD or null
  dental_injury_place    : string or null
  dental_injury_description : string or null
  dental_treatment_start : string  ISO date YYYY-MM-DD or null
  dental_treatment_end   : string  ISO date YYYY-MM-DD or null
  dental_cost            : number or null

--- SECTION 6: Receipt details ---
  receipts               : array of objects (up to 8 rows), each:
    {{ "treatment_type": string, "num_receipts": integer, "total_cost": number }}
  (empty array [] if none)
  receipts_total_cost    : number  (sum across all rows, or null)

--- SECTION 7: Payment details ---
  account_holder_name    : string or null
  account_number         : string or null
  bank_sort_code         : string or null  (format "XX-XX-XX")
  bank_name_address      : string or null

--- SECTION 8 / Meta ---
  declaration_date       : string  ISO date YYYY-MM-DD or null
  doc_category           : string  always "claim_form" for this document
  confidence             : float   0.0–1.0  overall extraction confidence

Email subject: {subject}
Email body (first 800 chars):
\"\"\"
{body_excerpt}
\"\"\"

{attachment_section}

Respond ONLY with JSON matching this exact key set (nulls/empty arrays for \
missing fields):
{{
  "membership_no":            ...,
  "title":                    ...,
  "surname":                  ...,
  "forenames":                ...,
  "date_of_birth":            ...,
  "telephone":                ...,
  "correspondence_address":   ...,
  "dependants":               [...],
  "mri_date":                 ...,
  "mri_reason_for_referral":  ...,
  "mri_centre":               ...,
  "mri_procedure":            ...,
  "mri_referring_gp":         ...,
  "mri_consultant_code":      ...,
  "accident_date":            ...,
  "accident_description":     ...,
  "expenses_recoverable":     ...,
  "recovery_via_solicitor":   ...,
  "recovery_via_piab":        ...,
  "third_party_details":      ...,
  "dental_injury_date":       ...,
  "dental_injury_place":      ...,
  "dental_injury_description": ...,
  "dental_treatment_start":   ...,
  "dental_treatment_end":     ...,
  "dental_cost":              ...,
  "receipts":                 [...],
  "receipts_total_cost":      ...,
  "account_holder_name":      ...,
  "account_number":           ...,
  "bank_sort_code":           ...,
  "bank_name_address":        ...,
  "declaration_date":         ...,
  "doc_category":             "claim_form",
  "confidence":               ...
}}""".strip()


# ══════════════════════════════════════════════════════════════════════════════
# Public Lambda handler
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Entry point called by Step Functions.
    Returns entity extraction result stored at ResultPath $.entities.
    """
    email_id = event.get("email_id", "unknown")

    logger.info(json.dumps({
        "trace_id":       email_id,
        "step":           "extract_entity",
        "has_attachment": event.get("has_attachment", False),
    }))

    # ── 1. Seed base entities from email_parser output ────────────────────────
    base_entities = {
        "policy_number": event.get("policy_number") or None,
        "member_id":     event.get("member_id")     or None,
        "customer_id":   event.get("customer_id")   or None,
        "sender_email":  str(event.get("sender_email") or ""),
        "pii_present":   bool(event.get("pii_present", False)),
    }

    # ── 2. Collect pre-extracted attachment text ──────────────────────────────
    email_body: str             = str(event.get("email_body") or "")
    subject:    str             = str(event.get("subject")    or "")
    sources_used: List[str]     = []
    text_chunks:  List[str]     = []
    textract_used: bool         = False

    if email_body.strip():
        sources_used.append("email_body")

    attachments_content: List[Dict] = event.get("attachments_content") or []
    for att in attachments_content:
        raw = (att.get("raw_text") or "").strip()
        if raw:
            category = att.get("doc_category", "unknown")
            text_chunks.append(f"[Attachment – {category}]\n{raw[:2000]}")
            if "attachment_text" not in sources_used:
                sources_used.append("attachment_text")

    # ── 3. Textract for image / scanned-PDF attachments ───────────────────────
    # Only triggered when the email has attachments but email_parser produced
    # no text (i.e. attachments were images that PyPDF2/docx couldn't handle).
    if event.get("has_attachment") and not text_chunks:
        bucket = str(event.get("s3_bucket") or "")
        key    = str(event.get("s3_key")    or "")
        ocr_chunks = _run_textract_on_email(bucket, key, email_id)
        if ocr_chunks:
            text_chunks.extend(ocr_chunks)
            sources_used.append("textract")
            textract_used = True

    # ── 4. Bedrock structured extraction ──────────────────────────────────────
    extracted_fields:      Dict[str, Any] = {}
    bedrock_used:          bool           = False
    extraction_confidence: float          = 0.5

    if email_body.strip() or text_chunks:
        extracted_fields, extraction_confidence, bedrock_used = _extract_via_bedrock(
            subject     = subject,
            email_body  = email_body,
            text_chunks = text_chunks,
            email_id    = email_id,
        )
        # Promote identifiers only if email_parser didn't already find them
        for field in ("policy_number", "member_id", "customer_id"):
            if not base_entities[field] and extracted_fields.get(field):
                base_entities[field] = extracted_fields.pop(field)
            else:
                extracted_fields.pop(field, None)  # avoid duplication

    # ── 5. Compose result ─────────────────────────────────────────────────────
    result: Dict[str, Any] = {
        **base_entities,
        "extracted_fields":      extracted_fields,
        "textract_used":         textract_used,
        "bedrock_used":          bedrock_used,
        "extraction_confidence": extraction_confidence,
        "sources":               list(dict.fromkeys(sources_used)),
    }

    logger.info(json.dumps({
        "trace_id":   email_id,
        "step":       "extract_entity",
        "sources":    result["sources"],
        "textract":   textract_used,
        "bedrock":    bedrock_used,
        "confidence": extraction_confidence,
    }))

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Textract pipeline
# ══════════════════════════════════════════════════════════════════════════════

def _run_textract_on_email(bucket: str, key: str, email_id: str) -> List[str]:
    """
    Fetch the raw MIME email from S3, find image / PDF attachments and extract
    text from each one.

    Strategy per attachment type:
      PDF  → 1) pypdf text extraction (fast, works for text-layer PDFs)
               2) fall back to Textract via S3Object if pypdf returns nothing
                  (handles scanned/image-only PDFs)
      Image → Textract DetectDocumentText with Bytes
              (DetectDocumentText only accepts raw bytes for JPEG/PNG/TIFF,
               NOT for PDF — that's why PDFs take the S3 path above)
    """
    if not bucket or not key:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "textract_skipped_no_s3_coords",
        }))
        return []

    try:
        obj      = s3.get_object(Bucket=bucket, Key=key)
        raw_mime = obj["Body"].read()
    except ClientError as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "s3_fetch_failed",
            "error":    exc.response["Error"]["Message"],
        }))
        return []

    results: List[str] = []
    try:
        msg = _email_lib.message_from_bytes(raw_mime)
        for part in msg.walk():
            cd       = str(part.get("Content-Disposition", ""))
            ct       = str(part.get("Content-Type", "")).split(";")[0].strip().lower()
            filename = part.get_filename() or ""

            # Accept both "attachment" and "inline" dispositions — some clients
            # send PDFs as inline rather than attachment.
            if "attachment" not in cd and "inline" not in cd:
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            is_pdf   = ext == "pdf"   or ct in _PDF_CONTENT_TYPES
            is_image = ext in _IMAGE_EXTENSIONS or ct in _IMAGE_CONTENT_TYPES

            if is_pdf:
                text = _extract_pdf_text(payload, filename, bucket, email_id)
                if text:
                    results.append(f"[PDF: {filename}]\n{text}")
            elif is_image:
                text = _textract_image_bytes(payload, filename, email_id)
                if text:
                    results.append(f"[Image OCR: {filename}]\n{text}")

    except Exception as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "mime_parse_failed",
            "error":    str(exc),
        }))

    return results


def _extract_pdf_text(
    payload: bytes, filename: str, bucket: str, email_id: str
) -> str:
    """
    Extract text from a PDF attachment.

    Step 1 – pypdf (fast, zero cost):
      Works for any PDF with a text layer (ReportLab-generated, Word export,
      etc.).  Returns the concatenated text of all pages.

    Step 2 – Textract via S3Object (fallback for scanned / image-only PDFs):
      Uploads the PDF to a temp S3 key, calls DetectDocumentText with an
      S3Object reference (the only mode Textract supports for PDFs), then
      deletes the temp object.
      NOTE: DetectDocumentText with Document={"Bytes": ...} does NOT accept
      PDFs — only JPEG/PNG/TIFF — hence the S3 detour for PDFs.
    """
    # ── Step 1: pypdf text layer extraction ───────────────────────────────────
    try:
        import pypdf as _pypdf
        reader = _pypdf.PdfReader(io.BytesIO(payload))
        pages_text = []
        for page in reader.pages:
            pt = page.extract_text() or ""
            if pt.strip():
                pages_text.append(pt.strip())
        combined = "\n".join(pages_text).strip()
        if combined:
            logger.info(json.dumps({
                "trace_id": email_id,
                "op":       "pypdf_extract",
                "filename": filename,
                "chars":    len(combined),
            }))
            return combined
    except Exception as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "pypdf_extract_failed",
            "filename": filename,
            "error":    str(exc),
        }))

    # ── Step 2: Textract via S3Object (scanned PDF fallback) ──────────────────
    if len(payload) > 5 * 1024 * 1024:
        logger.warning(json.dumps({
            "trace_id":   email_id,
            "warning":    "textract_pdf_skipped_too_large",
            "filename":   filename,
            "size_bytes": len(payload),
        }))
        return ""

    temp_key = f"tmp/textract/{email_id}/{filename}"
    try:
        s3.put_object(Bucket=bucket, Key=temp_key, Body=payload)
        t0   = time.monotonic()
        resp = textract.detect_document_text(
            Document={"S3Object": {"Bucket": bucket, "Name": temp_key}}
        )
        lines = [
            block["Text"]
            for block in resp.get("Blocks", [])
            if block["BlockType"] == "LINE"
        ]
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(json.dumps({
            "trace_id":   email_id,
            "op":         "textract_pdf_s3",
            "filename":   filename,
            "lines":      len(lines),
            "latency_ms": latency_ms,
        }))
        return "\n".join(lines)
    except ClientError as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "textract_pdf_failed",
            "filename": filename,
            "error":    exc.response["Error"]["Message"],
        }))
        return ""
    except Exception as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "textract_pdf_unexpected_error",
            "filename": filename,
            "error":    str(exc),
        }))
        return ""
    finally:
        # Always clean up the temp object
        try:
            s3.delete_object(Bucket=bucket, Key=temp_key)
        except Exception:
            pass


def _textract_image_bytes(payload: bytes, filename: str, email_id: str) -> str:
    """
    Call Textract DetectDocumentText with raw image bytes (JPEG/PNG/TIFF).
    The Bytes mode is only supported for images, not PDFs.
    Payloads over 5 MB are skipped (Textract synchronous API limit).
    """
    if len(payload) > 5 * 1024 * 1024:
        logger.warning(json.dumps({
            "trace_id":   email_id,
            "warning":    "textract_image_skipped_too_large",
            "filename":   filename,
            "size_bytes": len(payload),
        }))
        return ""

    t0 = time.monotonic()
    try:
        resp  = textract.detect_document_text(Document={"Bytes": payload})
        lines = [
            block["Text"]
            for block in resp.get("Blocks", [])
            if block["BlockType"] == "LINE"
        ]
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(json.dumps({
            "trace_id":   email_id,
            "op":         "textract_image_bytes",
            "filename":   filename,
            "lines":      len(lines),
            "latency_ms": latency_ms,
        }))
        return "\n".join(lines)
    except ClientError as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "textract_image_failed",
            "filename": filename,
            "error":    exc.response["Error"]["Message"],
        }))
        return ""
    except Exception as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "textract_image_unexpected_error",
            "filename": filename,
            "error":    str(exc),
        }))
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# Bedrock structured extraction
# ══════════════════════════════════════════════════════════════════════════════

def _extract_via_bedrock(
    subject:     str,
    email_body:  str,
    text_chunks: List[str],
    email_id:    str,
) -> Tuple[Dict[str, Any], float, bool]:
    """
    Call Bedrock Claude 3 Haiku to extract structured insurance fields.
    Returns (extracted_fields, confidence, was_called).
    Never raises — returns empty dict on any failure.
    """
    if text_chunks:
        combined           = "\n\n".join(text_chunks[:3])[:3000]
        attachment_section = f"Attachment content:\n\"\"\"\n{combined}\n\"\"\""
    else:
        attachment_section = "No attachment content available."

    prompt = _EXTRACTION_PROMPT.format(
        subject            = subject[:200],
        body_excerpt       = email_body[:800].replace('"', "'"),
        attachment_section = attachment_section,
    )

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens":        512,
        "temperature":       0.0,
        "messages":          [{"role": "user", "content": prompt}],
    })

    t0 = time.monotonic()
    try:
        resp     = bedrock.invoke_model(
            modelId     = ENTITY_MODEL_ID,
            body        = body,
            contentType = "application/json",
            accept      = "application/json",
        )
        raw      = json.loads(resp["body"].read())
        text_out = raw["content"][0]["text"]
    except Exception as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "bedrock_extraction_failed",
            "error":    str(exc),
        }))
        return {}, 0.5, False

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(json.dumps({
        "trace_id":   email_id,
        "op":         "bedrock_extract",
        "model":      ENTITY_MODEL_ID,
        "latency_ms": latency_ms,
    }))

    fields, confidence = _parse_extraction_json(text_out, email_id)
    return fields, confidence, True


def _parse_extraction_json(
    text: str, email_id: str
) -> Tuple[Dict[str, Any], float]:
    """
    Extract the first JSON object from Bedrock's output.
    Returns (fields_dict, confidence). Never raises.
    """
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "no_json_in_bedrock_output",
        }))
        return {}, 0.5

    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "bedrock_json_parse_error",
            "error":    str(exc),
        }))
        return {}, 0.5

    raw_conf   = obj.pop("confidence", 0.7)
    confidence = max(0.0, min(1.0, float(raw_conf)))

    # Strip null / empty-string scalar values; keep arrays (even empty ones)
    # and booleans (False is a valid value, not "missing").
    fields = {
        k: v
        for k, v in obj.items()
        if isinstance(v, (list, bool)) or (v is not None and v != "" and v != "null")
    }
    return fields, confidence
