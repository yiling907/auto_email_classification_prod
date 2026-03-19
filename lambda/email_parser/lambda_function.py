"""
Email Parser Lambda Function
Parses raw emails from S3 and extracts fields matching the emails.jsonl schema.
"""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from email import message_from_string
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Dict, Tuple

import boto3
from botocore.exceptions import ClientError
from decimal import Decimal

# ── AWS clients ───────────────────────────────────────────────────────────────
s3_client = boto3.client('s3')
dynamodb  = boto3.resource('dynamodb')

# ── Environment variables ─────────────────────────────────────────────────────
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']
email_table      = dynamodb.Table(EMAIL_TABLE_NAME)

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


# ── Lambda handler ─────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler.  Accepts S3 events, SES SNS events, or direct
    {bucket, key} invocations.

    Returns {statusCode, email_id, parsed_data}.
    """
    try:
        if 'Records' in event:
            record = event['Records'][0]
            if 's3' in record:
                bucket = record['s3']['bucket']['name']
                key    = record['s3']['object']['key']
            elif 'Sns' in record:
                sns_message = json.loads(record['Sns']['Message'])
                action  = sns_message.get('receipt', {}).get('action', {})
                bucket  = action.get('bucketName')
                key     = action.get('objectKey')
            else:
                raise ValueError(
                    f"Unsupported Records event source: {record.get('eventSource', 'unknown')}"
                )
        else:
            bucket = event.get('bucket')
            key    = event.get('key')

        if not bucket or not key:
            raise ValueError("Missing bucket or key in event")

        print(f"Fetching email from s3://{bucket}/{key}")
        response  = s3_client.get_object(Bucket=bucket, Key=key)
        raw_email = response['Body'].read().decode('utf-8')

        parsed_data = parse_email(raw_email)
        print(f"[DEBUG] parse_email keys: {list(parsed_data.keys())}")
        print(f"[DEBUG] has_attachment={parsed_data.get('has_attachment')}, "
              f"attachment_count={parsed_data.get('attachment_count')}, "
              f"attachments_content present={('attachments_content' in parsed_data)}, "
              f"attachments_content={parsed_data.get('attachments_content')}")

        email_id = str(uuid.uuid4())
        parsed_data.update({
            'email_id':          email_id,
            's3_bucket':         bucket,
            's3_key':            key,
            'processing_status': 'parsed',
        })

        email_table.put_item(Item=_dynamo_safe(parsed_data))
        print(f"Stored email {email_id} in DynamoDB")

        result = {
            'statusCode':  200,
            'email_id':    email_id,
            'parsed_data': parsed_data,
        }
        print(f"[DEBUG] return keys: {list(result.keys())}")
        print(f"[DEBUG] parsed_data keys in return: {list(result['parsed_data'].keys())}")
        return result

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
