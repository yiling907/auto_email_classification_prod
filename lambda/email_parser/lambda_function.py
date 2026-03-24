"""
Email Parser Lambda Function
Parses raw emails from S3, extracts fields matching the emails.jsonl schema,
and runs entity extraction (Textract + Bedrock Claude) on any attachments.
"""
import io
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from email import message_from_string, message_from_bytes
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Dict, List, Tuple

import boto3
from botocore.exceptions import ClientError
from decimal import Decimal

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── AWS clients ───────────────────────────────────────────────────────────────
_REGION   = os.environ.get("AWS_REGION", "us-east-1")
s3_client = boto3.client('s3', region_name=_REGION)
dynamodb  = boto3.resource('dynamodb')
bedrock   = boto3.client("bedrock-runtime", region_name=_REGION)
textract  = boto3.client("textract",        region_name=_REGION)

# ── Environment variables ─────────────────────────────────────────────────────
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']
email_table      = dynamodb.Table(EMAIL_TABLE_NAME)
ENTITY_MODEL_ID  = os.environ.get(
    "ENTITY_MODEL_ID", "mistral.mistral-7b-instruct-v0:2"
)

# ── Medical terms for detection ───────────────────────────────────────────────
MEDICAL_TERMS = {
    'hospital', 'clinic', 'gp', 'doctor', 'consultant', 'surgery', 'procedure',
    'treatment', 'diagnosis', 'prescription', 'medication', 'referral', 'scan',
    'mri', 'xray', 'x-ray', 'ct scan', 'outpatient', 'inpatient', 'admission',
    'discharge', 'physiotherapy', 'orthopaedic', 'cardiac', 'oncology', 'cancer',
    'maternity', 'fertility', 'mental health', 'psychiatry', 'pathology', 'radiology',
    'anaesthetic', 'anaesthesia', 'pre-authorisation', 'pre-auth', 'preauth',
}

# ── Regex patterns for PII and policy/member extraction ───────────────────────
_RE_EMAIL  = re.compile(r'\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b')
_RE_PHONE  = re.compile(r'\b(\+353|0)\d[\d\s\-]{7,11}\b')
_RE_POLICY = re.compile(r'\bPOL-IE-\d{6}\b', re.IGNORECASE)
_RE_MEMBER = re.compile(r'\bMEM-\d{6}\b',    re.IGNORECASE)
_RE_PPSN   = re.compile(r'\b\d{7}[A-Z]{1,2}\b')

# ── MIME content types for Textract ───────────────────────────────────────────
_IMAGE_EXTENSIONS    = frozenset({"jpg", "jpeg", "png", "tiff", "tif"})
_IMAGE_CONTENT_TYPES = frozenset({
    "image/jpeg", "image/jpg", "image/png", "image/tiff",
})
_PDF_CONTENT_TYPES   = frozenset({"application/pdf"})

# ── Bedrock structured extraction prompt ──────────────────────────────────────
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


# ── DynamoDB type helpers ─────────────────────────────────────────────────────

def _dynamo_safe(obj: Any) -> Any:
    """Recursively convert float → Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _dynamo_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_dynamo_safe(i) for i in obj]
    return obj


# ── Unrelated email filter ────────────────────────────────────────────────────

_FILTER_KEYWORDS = frozenset({
    "github", "marketplace", "aws", "amazon", "notification", "alert",
})


def filter_unrelated_emails(email_data: dict) -> bool:
    """
    Return True if the email should be skipped (unrelated sender).
    Checks sender_email and sender_name against _FILTER_KEYWORDS (case-insensitive).
    """
    haystack = " ".join([
        (email_data.get("sender_email") or ""),
        (email_data.get("sender_name")  or ""),
    ]).lower()
    return any(kw in haystack for kw in _FILTER_KEYWORDS)


# ── Lambda handler ─────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler. Accepts direct {bucket, key} invocations.

    Parses the raw email from S3, runs Textract + Bedrock entity extraction
    on any attachments, stores to DynamoDB, and returns
    {statusCode, email_id, parsed_data, entities}.
    """
    try:
        bucket = event.get('bucket')
        key    = event.get('key')

        if not bucket or not key:
            raise ValueError("Missing bucket or key in event")

        print(f"Fetching email from s3://{bucket}/{key}")
        response  = s3_client.get_object(Bucket=bucket, Key=key)
        raw_email = response['Body'].read().decode('utf-8')

        parsed_data = parse_email(raw_email)

        # ── Unrelated email filter ─────────────────────────────────────────────
        if filter_unrelated_emails(parsed_data):
            print(f"Filtered unrelated email from: {redact_pii(parsed_data.get('sender_email', ''))}")
            return {'statusCode': 200, 'filtered': True, 'reason': 'unrelated_sender'}

        email_id = str(uuid.uuid4())
        parsed_data.update({
            'email_id':          email_id,
            's3_bucket':         bucket,
            's3_key':            key,
            'processing_status': 'parsed',
        })

        # ── Entity extraction (Textract + Bedrock) ────────────────────────────
        entities = _extract_entities(
            email_id      = email_id,
            email_body    = parsed_data['body_text'],
            subject       = parsed_data['subject'],
            sender_email  = parsed_data['sender_email'],
            policy_number = parsed_data['policy_number'],
            member_id     = parsed_data['member_id'],
            customer_id   = parsed_data['customer_id'],
            pii_present   = parsed_data['pii_present'],
            has_attachment = parsed_data['has_attachment'],
            bucket        = bucket,
            key           = key,
        )
        parsed_data['entities'] = entities

        email_table.put_item(Item=_dynamo_safe(parsed_data))
        print(f"Stored email {email_id} in DynamoDB")

        return {
            'statusCode':  200,
            'email_id':    email_id,
            'parsed_data': parsed_data,
            'entities':    entities,
        }

    except ClientError as e:
        print(f"AWS Error: {str(e)}")
        raise
    except Exception as e:
        print(f"Error: {str(e)}")
        raise


# ── Core parse function ───────────────────────────────────────────────────────

def parse_email(raw_email: str) -> Dict[str, Any]:
    """
    Parse a raw RFC-2822 email string.

    Returns a dict whose field names match emails.jsonl.
    """
    msg = message_from_string(raw_email)

    # ── Sender / recipient ────────────────────────────────────────────────────
    sender_name,  sender_email = parseaddr(msg.get('From', ''))
    _,            to_address   = parseaddr(msg.get('To', ''))

    # ── Timestamp ─────────────────────────────────────────────────────────────
    received_at = _parse_date(msg.get('Date', ''))

    # ── Thread metadata ───────────────────────────────────────────────────────
    thread_id     = _extract_thread_id(msg)
    message_index = _extract_message_index(msg)

    # ── Subject & body ────────────────────────────────────────────────────────
    subject              = msg.get('Subject', '')
    body_text, body_html = _extract_bodies(msg)

    if not sender_email or not body_text:
        raise ValueError("Invalid email: missing sender or body")

    print(f"Parsed email from: {redact_pii(sender_email)} to: {redact_pii(to_address)}")

    # ── Attachments ───────────────────────────────────────────────────────────
    attachment_count, has_attachment = _count_attachments(msg)

    # ── Entity extraction from body + subject ─────────────────────────────────
    full_text     = f"{subject} {body_text}"
    policy_number = _extract_policy_number(full_text)
    member_id     = _extract_member_id(full_text)

    # ── PII / medical flags ────────────────────────────────────────────────────
    pii_present           = _detect_pii(full_text)
    medical_terms_present = _detect_medical_terms(full_text)

    return {
        # Thread / routing metadata
        'thread_id':     thread_id,
        'message_index': message_index,
        'received_at':   received_at,
        'channel':       'email',
        'mailbox':       to_address,

        # Sender
        'sender_name':  sender_name,
        'sender_email': sender_email,

        # Customer identifiers
        'customer_id':   '',
        'member_id':     member_id,
        'policy_number': policy_number,

        # Content
        'subject':   subject,
        'body_text': body_text,
        'body_html': body_html,

        # Language
        'detected_language': 'en',

        # Classification labels — set by classify_intent Lambda
        'customer_intent':  '',
        'secondary_intent': '',
        'business_line':    '',
        'urgency':          '',
        'sentiment':        '',

        # Attachments
        'has_attachment':      has_attachment,
        'attachment_count':    attachment_count,
        'attachments_content': [],

        # Routing labels — set by classify_intent Lambda
        'requires_human_review': True,
        'gold_route_team':       '',
        'gold_priority':         '',

        # Content flags
        'pii_present':           pii_present,
        'medical_terms_present': medical_terms_present,

        # Demo / processing state
        'status_in_demo':  'new',
        'confidence_level': 'pending',
    }


# ── Email structure helpers ────────────────────────────────────────────────────

def _parse_date(date_str: str) -> str:
    if not date_str:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except Exception:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _extract_thread_id(msg) -> str:
    references = msg.get('References', '')
    if references:
        first = references.strip().split()[0]
        return first.strip('<>') if first else str(uuid.uuid4())
    message_id = msg.get('Message-ID', '')
    return message_id.strip('<>') if message_id else str(uuid.uuid4())


def _extract_message_index(msg) -> int:
    references = msg.get('References', '')
    return len(references.strip().split()) + 1 if references else 1


def _extract_bodies(msg) -> Tuple[str, str]:
    body_text = ''
    body_html = ''
    if msg.is_multipart():
        for part in msg.walk():
            ct  = part.get_content_type()
            cd  = str(part.get('Content-Disposition', ''))
            if 'attachment' in cd:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or 'utf-8'
            decoded = payload.decode(charset, errors='ignore')
            if ct == 'text/plain' and not body_text:
                body_text = decoded
            elif ct == 'text/html' and not body_html:
                body_html = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or 'utf-8'
            text    = payload.decode(charset, errors='ignore')
            if msg.get_content_type() == 'text/html':
                body_html = text
            else:
                body_text = text
    return body_text, body_html


def _count_attachments(msg) -> Tuple[int, bool]:
    count = 0
    if msg.is_multipart():
        for part in msg.walk():
            if 'attachment' in str(part.get('Content-Disposition', '')):
                count += 1
    return count, count > 0


def _extract_policy_number(text: str) -> str:
    m = _RE_POLICY.search(text)
    return m.group(0).upper() if m else ''


def _extract_member_id(text: str) -> str:
    m = _RE_MEMBER.search(text)
    return m.group(0).upper() if m else ''


def _detect_pii(text: str) -> bool:
    return bool(_RE_EMAIL.search(text) or _RE_PHONE.search(text) or _RE_PPSN.search(text))


def _detect_medical_terms(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in MEDICAL_TERMS)


def redact_pii(text: str) -> str:
    """Redact email addresses for log output (never stored)."""
    return re.sub(r'(\w{1,3})\w+@', r'\1***@', text)


# ══════════════════════════════════════════════════════════════════════════════
# Entity extraction (merged from extract_entity Lambda)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_entities(
    email_id:      str,
    email_body:    str,
    subject:       str,
    sender_email:  str,
    policy_number: str,
    member_id:     str,
    customer_id:   str,
    pii_present:   bool,
    has_attachment: bool,
    bucket:        str,
    key:           str,
) -> Dict[str, Any]:
    """
    Run Textract + Bedrock Claude entity extraction on the email and its
    attachments.  Returns an entities dict (never raises).
    """
    logger.info(json.dumps({
        "trace_id":       email_id,
        "step":           "extract_entities",
        "has_attachment": has_attachment,
    }))

    # Seed base entities from email_parser regex output
    base_entities: Dict[str, Any] = {
        "policy_number": policy_number or None,
        "member_id":     member_id     or None,
        "customer_id":   customer_id   or None,
        "sender_email":  sender_email,
        "pii_present":   pii_present,
    }

    sources_used:  List[str] = []
    text_chunks:   List[str] = []
    textract_used: bool      = False

    if email_body.strip():
        sources_used.append("email_body")

    if has_attachment:
        ocr_chunks = _run_textract_on_email(bucket, key, email_id)
        if ocr_chunks:
            text_chunks.extend(ocr_chunks)
            sources_used.append("textract")
            textract_used = True

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
        # Promote identifiers only if regex didn't already find them
        for field in ("policy_number", "member_id", "customer_id"):
            if not base_entities[field] and extracted_fields.get(field):
                base_entities[field] = extracted_fields.pop(field)
            else:
                extracted_fields.pop(field, None)

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
        "step":       "extract_entities",
        "sources":    result["sources"],
        "textract":   textract_used,
        "bedrock":    bedrock_used,
        "confidence": extraction_confidence,
    }))

    return result


# ── Textract pipeline ──────────────────────────────────────────────────────────

def _run_textract_on_email(bucket: str, key: str, email_id: str) -> List[str]:
    """
    Fetch the raw MIME email from S3, find image/PDF attachments and extract
    text from each via Textract / pypdf.
    """
    if not bucket or not key:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "textract_skipped_no_s3_coords",
        }))
        return []

    try:
        obj      = s3_client.get_object(Bucket=bucket, Key=key)
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
        msg = message_from_bytes(raw_mime)
        for part in msg.walk():
            cd       = str(part.get("Content-Disposition", ""))
            ct       = str(part.get("Content-Type", "")).split(";")[0].strip().lower()
            filename = part.get_filename() or ""

            if "attachment" not in cd and "inline" not in cd:
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            ext      = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
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
    Step 1: pypdf text-layer extraction (fast, zero cost).
    Step 2: Textract via S3Object fallback for scanned/image-only PDFs.
    """
    try:
        import pypdf as _pypdf
        reader     = _pypdf.PdfReader(io.BytesIO(payload))
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
                "pages":    len(reader.pages),
                "preview":  combined[:300],
            }))
            return combined
        else:
            logger.warning(json.dumps({
                "trace_id": email_id,
                "warning":  "pypdf_empty_text",
                "filename": filename,
                "pages":    len(reader.pages),
            }))
    except Exception as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "pypdf_extract_failed",
            "filename": filename,
            "error":    str(exc),
        }))

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
        s3_client.put_object(
            Bucket=bucket, Key=temp_key, Body=payload, ContentType="application/pdf"
        )
        t0   = time.monotonic()
        # Use async API — supports multi-page PDFs (detect_document_text only handles single-page)
        start_resp = textract.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": bucket, "Name": temp_key}}
        )
        job_id = start_resp["JobId"]
        # Poll until complete (max 60s)
        for _ in range(30):
            time.sleep(2)
            result = textract.get_document_text_detection(JobId=job_id)
            if result["JobStatus"] in ("SUCCEEDED", "FAILED"):
                break
        if result["JobStatus"] != "SUCCEEDED":
            raise RuntimeError(f"Textract job {job_id} status: {result['JobStatus']}")
        lines      = [b["Text"] for b in result.get("Blocks", []) if b["BlockType"] == "LINE"]
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(json.dumps({
            "trace_id":   email_id,
            "op":         "textract_pdf_async",
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
        try:
            s3_client.delete_object(Bucket=bucket, Key=temp_key)
        except Exception:
            pass


def _textract_image_bytes(payload: bytes, filename: str, email_id: str) -> str:
    """
    Call Textract DetectDocumentText with raw image bytes (JPEG/PNG/TIFF).
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
        resp       = textract.detect_document_text(Document={"Bytes": payload})
        lines      = [b["Text"] for b in resp.get("Blocks", []) if b["BlockType"] == "LINE"]
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


# ── Bedrock structured extraction ──────────────────────────────────────────────

def _extract_via_bedrock(
    subject:     str,
    email_body:  str,
    text_chunks: List[str],
    email_id:    str,
) -> Tuple[Dict[str, Any], float, bool]:
    """
    Call Bedrock Mistral 7B to extract structured insurance fields.
    Returns (extracted_fields, confidence, was_called).
    Never raises — returns empty dict on any failure.
    """
    if text_chunks:
        combined           = "\n\n".join(text_chunks[:3])[:8000]
        attachment_section = f"Attachment content:\n\"\"\"\n{combined}\n\"\"\""
        logger.info(json.dumps({
            "trace_id":           email_id,
            "op":                 "bedrock_input",
            "total_chunk_chars":  sum(len(c) for c in text_chunks),
            "truncated_to":       len(combined),
            "attachment_preview": combined[:300],
        }))
    else:
        attachment_section = "No attachment content available."
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "bedrock_no_attachment_text",
        }))

    prompt = _EXTRACTION_PROMPT.format(
        subject            = subject[:200],
        body_excerpt       = email_body[:800].replace('"', "'"),
        attachment_section = attachment_section,
    )

    body = json.dumps({
        "prompt":      f"<s>[INST] {prompt} [/INST]",
        "max_tokens":  2048,
        "temperature": 0.0,
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
        text_out = raw["outputs"][0]["text"]
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
    logger.info(json.dumps({
        "trace_id": email_id,
        "op":       "bedrock_raw_output",
        "text_out": text_out[:1000],
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

    # Mistral sometimes escapes underscores as \_ which is invalid JSON — strip the backslash
    json_str = match.group().replace("\\_", "_")
    try:
        obj = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.warning(json.dumps({
            "trace_id": email_id,
            "warning":  "bedrock_json_parse_error",
            "error":    str(exc),
        }))
        return {}, 0.5

    raw_conf   = obj.pop("confidence", 0.7) or 0.7
    confidence = max(0.0, min(1.0, float(raw_conf)))

    logger.info(json.dumps({
        "trace_id":           email_id,
        "op":                 "parse_extraction",
        "receipts_raw":       obj.get("receipts"),
        "receipts_total_raw": obj.get("receipts_total_cost"),
    }))

    # Strip null/empty scalars; keep arrays (even empty) and booleans
    fields = {
        k: v
        for k, v in obj.items()
        if isinstance(v, (list, bool)) or (v is not None and v != "" and v != "null")
    }
    logger.info(json.dumps({
        "trace_id":       email_id,
        "op":             "parse_extraction_result",
        "receipts_final": fields.get("receipts"),
        "field_keys":     list(fields.keys()),
    }))
    return fields, confidence
