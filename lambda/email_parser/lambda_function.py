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
from typing import Dict, Any, List, Optional
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']
email_table = dynamodb.Table(EMAIL_TABLE_NAME)

# Medical terms for detection
MEDICAL_TERMS = {
    'hospital', 'clinic', 'gp', 'doctor', 'consultant', 'surgery', 'procedure',
    'treatment', 'diagnosis', 'prescription', 'medication', 'referral', 'scan',
    'mri', 'xray', 'x-ray', 'ct scan', 'outpatient', 'inpatient', 'admission',
    'discharge', 'physiotherapy', 'orthopaedic', 'cardiac', 'oncology', 'cancer',
    'maternity', 'fertility', 'mental health', 'psychiatry', 'pathology', 'radiology',
    'anaesthetic', 'anaesthesia', 'pre-authorisation', 'pre-auth', 'preauth',
}

# Regex patterns for PII and policy/member extraction
_RE_EMAIL = re.compile(r'\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b')
_RE_PHONE = re.compile(r'\b(\+353|0)\d[\d\s\-]{7,11}\b')
_RE_POLICY = re.compile(r'\bPOL-IE-\d{6}\b', re.IGNORECASE)
_RE_MEMBER = re.compile(r'\bMEM-\d{6}\b', re.IGNORECASE)
_RE_PPSN = re.compile(r'\b\d{7}[A-Z]{1,2}\b')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for email parsing.

    Args:
        event: S3 event or direct invocation with bucket/key
        context: Lambda context

    Returns:
        Dict with parsed email data and email_id
    """
    try:
        # Extract bucket and key from event
        if 'Records' in event:
            record = event['Records'][0]
            ## todo: check
            if 's3' in record:
                bucket = record['s3']['bucket']['name']
                key = record['s3']['object']['key']
            elif 'Sns' in record:
                sns_message = json.loads(record['Sns']['Message'])
                action = sns_message.get('receipt', {}).get('action', {})
                bucket = action.get('bucketName')
                key = action.get('objectKey')
            else:
                raise ValueError(f"Unsupported Records event source: {record.get('eventSource', 'unknown')}")
        else:
            bucket = event.get('bucket')
            key = event.get('key')

        if not bucket or not key:
            raise ValueError("Missing bucket or key in event")

        print(f"Fetching email from s3://{bucket}/{key}")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        raw_email = response['Body'].read().decode('utf-8')

        parsed_data = parse_email(raw_email)

        email_id = str(uuid.uuid4())
        parsed_data.update({
            'email_id': email_id,
            's3_bucket': bucket,
            's3_key': key,
            'processing_status': 'parsed',
        })

        email_table.put_item(Item=parsed_data)
        print(f"Stored email {email_id} in DynamoDB")

        return {
            'statusCode': 200,
            'email_id': email_id,
            'parsed_data': parsed_data,
        }

    except ClientError as e:
        print(f"AWS Error: {str(e)}")
        raise
    except Exception as e:
        print(f"Error: {str(e)}")
        raise


def parse_email(raw_email: str) -> Dict[str, Any]:
    """
    Parse raw email text and extract all fields matching the emails.jsonl schema.

    Returns a dict with the same field names used in the synthetic dataset so that
    downstream Lambdas (classify_intent, claude_response, etc.) can read them
    without field-name translation.
    """
    msg = message_from_string(raw_email)

    # ── Sender / recipient ──────────────────────────────────────────────────
    sender_name, sender_email = parseaddr(msg.get('From', ''))
    _, to_address = parseaddr(msg.get('To', ''))

    # ── Timestamp ────────────────────────────────────────────────────────────
    received_at = _parse_date(msg.get('Date', ''))

    # ── Thread / message index ───────────────────────────────────────────────
    thread_id = _extract_thread_id(msg)
    message_index = _extract_message_index(msg)

    # ── Subject ──────────────────────────────────────────────────────────────
    subject = msg.get('Subject', '')

    # ── Body (plain text + HTML) ─────────────────────────────────────────────
    body_text, body_html = _extract_bodies(msg)

    if not sender_email or not body_text:
        raise ValueError("Invalid email: missing sender or body")

    print(f"Parsed email from: {redact_pii(sender_email)} to: {redact_pii(to_address)}")

    # ── Attachments ──────────────────────────────────────────────────────────
    attachment_count, has_attachment = _count_attachments(msg)

    # ── Entity extraction from body + subject ────────────────────────────────
    full_text = f"{subject} {body_text}"
    policy_number = _extract_policy_number(full_text)
    member_id = _extract_member_id(full_text)

    # ── PII / medical detection ──────────────────────────────────────────────
    pii_present = _detect_pii(full_text)
    medical_terms_present = _detect_medical_terms(full_text)

    return {
        # Thread / routing metadata
        'thread_id': thread_id,
        'message_index': message_index,
        'received_at': received_at,
        'channel': 'email',
        'mailbox': to_address,

        # Sender
        'sender_name': sender_name,
        'sender_email': sender_email,

        # Customer identifiers (populated where detectable; enriched later by CRM lookup)
        'customer_id': '',
        'member_id': member_id,
        'policy_number': policy_number,

        # Content
        'subject': subject,
        'body_text': body_text,
        'body_html': body_html,

        # Language
        'detected_language': 'en',

        # Classification gold labels — set by classify_intent Lambda, not the parser
        'customer_intent': '',
        'secondary_intent': '',
        'business_line': '',
        'urgency': '',
        'sentiment': '',

        # Attachments
        'has_attachment': has_attachment,
        'attachment_count': attachment_count,

        # Routing gold labels — set by classify_intent Lambda
        'requires_human_review': True,
        'gold_route_team': '',
        'gold_priority': '',

        # Content flags
        'pii_present': pii_present,
        'medical_terms_present': medical_terms_present,

        # Demo / processing state
        'status_in_demo': 'new',
        'confidence_level': 'pending',
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_date(date_str: str) -> str:
    """Convert RFC 2822 email date to ISO 8601 UTC string."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except Exception:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _extract_thread_id(msg) -> str:
    """Derive a thread ID from References or Message-ID headers."""
    references = msg.get('References', '')
    if references:
        # First Message-ID in References is the thread root
        first = references.strip().split()[0]
        return first.strip('<>') if first else str(uuid.uuid4())
    message_id = msg.get('Message-ID', '')
    return message_id.strip('<>') if message_id else str(uuid.uuid4())


def _extract_message_index(msg) -> int:
    """Return position of this message in thread (1 = first)."""
    references = msg.get('References', '')
    if not references:
        return 1
    return len(references.strip().split()) + 1


def _extract_bodies(msg) -> tuple:
    """Return (plain_text_body, html_body) from a parsed email message."""
    body_text = ''
    body_html = ''

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get('Content-Disposition', ''))
            if 'attachment' in cd:
                continue
            if ct == 'text/plain' and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(part.get_content_charset() or 'utf-8', errors='ignore')
            elif ct == 'text/html' and not body_html:
                payload = part.get_payload(decode=True)
                if payload:
                    body_html = payload.decode(part.get_content_charset() or 'utf-8', errors='ignore')
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(msg.get_content_charset() or 'utf-8', errors='ignore')
            if msg.get_content_type() == 'text/html':
                body_html = text
            else:
                body_text = text

    return body_text, body_html


def _count_attachments(msg) -> tuple:
    """Return (count, has_attachment) for non-inline attachments."""
    count = 0
    if msg.is_multipart():
        for part in msg.walk():
            cd = str(part.get('Content-Disposition', ''))
            if 'attachment' in cd:
                count += 1
    return count, count > 0


def _extract_policy_number(text: str) -> str:
    """Extract first POL-IE-XXXXXX pattern from text."""
    match = _RE_POLICY.search(text)
    return match.group(0).upper() if match else ''


def _extract_member_id(text: str) -> str:
    """Extract first MEM-XXXXXX pattern from text."""
    match = _RE_MEMBER.search(text)
    return match.group(0).upper() if match else ''


def _detect_pii(text: str) -> bool:
    """Return True if the text contains email addresses, phone numbers, or PPSN."""
    return bool(
        _RE_EMAIL.search(text)
        or _RE_PHONE.search(text)
        or _RE_PPSN.search(text)
    )


def _detect_medical_terms(text: str) -> bool:
    """Return True if the text contains any recognised medical term."""
    lower = text.lower()
    return any(term in lower for term in MEDICAL_TERMS)


def redact_pii(text: str) -> str:
    """Redact email addresses for log output (logging only — not stored)."""
    return re.sub(r'(\w{1,3})\w+@', r'\1***@', text)
