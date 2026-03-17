"""
Email Parser Lambda Function
Parses raw emails from S3 and extracts fields matching the emails.jsonl schema.

Attachment parsing extension:
  Each attachment is text-extracted (PDF via PyPDF2, DOCX via python-docx,
  TXT via stdlib) then classified into one of 14 doc_category values.
  Structured fields are extracted per category using regex patterns.
  The output `attachments_content` list matches the attachment_content.jsonl
  schema exactly:

      [
        {
          "raw_text_id":          "OCR-<uuid>",
          "attachment_id":        "ATT-<uuid>",
          "doc_category":         "<category>",
          "raw_text":             "<extracted text>",
          "structured_gold_fields": { ... }  # category-specific keys
        },
        ...
      ]
"""
import io
import json
import os
import re
import uuid
from datetime import datetime, timezone
from email import message_from_string
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from decimal import Decimal

# Optional heavy-weight imports — handled gracefully when unavailable in Lambda
try:
    import PyPDF2
    _PYPDF2_AVAILABLE = True
except ImportError:
    try:
        from pypdf import PdfReader as _PdfReader   # pypdf is the modern fork
        _PYPDF2_AVAILABLE = False
        _PYPDF_AVAILABLE  = True
    except ImportError:
        _PYPDF2_AVAILABLE = False
        _PYPDF_AVAILABLE  = False
else:
    _PYPDF_AVAILABLE = False

try:
    import docx as _docx
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False

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

    Returns {statusCode, email_id, parsed_data} where parsed_data now
    includes an `attachments_content` list matching attachment_content.jsonl.
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

        email_id = str(uuid.uuid4())
        parsed_data.update({
            'email_id':          email_id,
            's3_bucket':         bucket,
            's3_key':            key,
            'processing_status': 'parsed',
        })

        email_table.put_item(Item=_dynamo_safe(parsed_data))
        print(f"Stored email {email_id} in DynamoDB")

        return {
            'statusCode':  200,
            'email_id':    email_id,
            'parsed_data': parsed_data,
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
    The new `attachments_content` key holds a list of dicts matching
    attachment_content.jsonl — one entry per successfully-parsed attachment.
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

    # ── Attachments — text extraction + structured parsing ────────────────────
    attachment_count, has_attachment = _count_attachments(msg)
    attachments_content              = parse_attachments(msg)

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

        # Attachments — count flags (backward compat) + full parsed content
        'has_attachment':    has_attachment,
        'attachment_count':  attachment_count,
        'attachments_content': attachments_content,   # matches attachment_content.jsonl

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


# ── Attachment parsing ─────────────────────────────────────────────────────────

def parse_attachments(msg) -> List[Dict[str, Any]]:
    """
    Walk a parsed email message and extract text from every attachment.

    Supported file types: PDF (.pdf), plain text (.txt), Word (.docx).
    Unsupported types (PNG, JPG, etc.) are skipped gracefully.

    Returns a list of dicts, each matching the attachment_content.jsonl schema:
        {
          "raw_text_id":          str,   # "OCR-<uuid8>"
          "attachment_id":        str,   # "ATT-<uuid8>"
          "doc_category":         str,   # one of the 14 recognised categories
          "raw_text":             str,   # full extracted text
          "structured_gold_fields": dict # category-specific extracted fields
        }
    """
    results: List[Dict[str, Any]] = []

    if not msg.is_multipart():
        return results

    for part in msg.walk():
        # Only process parts marked as attachments
        content_disposition = str(part.get('Content-Disposition', ''))
        if 'attachment' not in content_disposition:
            continue

        filename     = part.get_filename() or ''
        content_type = part.get_content_type()
        payload      = part.get_payload(decode=True)

        if not payload:
            continue

        # ── Extract raw text based on file type ───────────────────────────────
        ext      = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        raw_text = _extract_text(payload, ext, content_type, filename)

        if raw_text is None:
            # Unsupported type — skip silently
            continue

        # ── Classify and extract structured fields ─────────────────────────────
        doc_category = _classify_doc_category(filename, raw_text)
        structured   = _extract_structured_fields(doc_category, raw_text)

        results.append({
            'raw_text_id':          f"OCR-{uuid.uuid4().hex[:8].upper()}",
            'attachment_id':        f"ATT-{uuid.uuid4().hex[:8].upper()}",
            'doc_category':         doc_category,
            'raw_text':             raw_text.strip(),
            'structured_gold_fields': structured,
        })

        print(
            f"Parsed attachment '{filename}' → "
            f"category={doc_category} text_len={len(raw_text)}"
        )

    return results


# ── Text extraction by file type ───────────────────────────────────────────────

def _extract_text(
    payload: bytes,
    ext: str,
    content_type: str,
    filename: str,
) -> Optional[str]:
    """
    Dispatch to the correct extractor based on file extension / MIME type.

    Returns extracted text string, or None if the type is unsupported.
    """
    # Normalise: prefer extension, fall back to MIME
    if ext == 'pdf' or content_type == 'application/pdf':
        return _extract_pdf(payload)

    if ext == 'docx' or content_type in (
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/msword',
    ):
        return _extract_docx(payload)

    if ext == 'txt' or content_type == 'text/plain':
        return _extract_txt(payload)

    # Unsupported (PNG, JPG, etc.) — caller skips
    return None


def _extract_pdf(payload: bytes) -> str:
    """Extract all text from a PDF byte payload using PyPDF2 / pypdf."""
    if _PYPDF2_AVAILABLE:
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(payload))
            pages  = [reader.pages[i].extract_text() or '' for i in range(len(reader.pages))]
            return '\n'.join(pages).strip()
        except Exception as e:
            print(f"PyPDF2 extraction failed: {e}")
            return ''

    if _PYPDF_AVAILABLE:
        try:
            reader = _PdfReader(io.BytesIO(payload))
            pages  = [p.extract_text() or '' for p in reader.pages]
            return '\n'.join(pages).strip()
        except Exception as e:
            print(f"pypdf extraction failed: {e}")
            return ''

    print("WARNING: No PDF library available — returning empty text for PDF attachment")
    return ''


def _extract_docx(payload: bytes) -> str:
    """Extract all paragraph text from a DOCX byte payload using python-docx."""
    if not _DOCX_AVAILABLE:
        print("WARNING: python-docx not available — returning empty text for DOCX attachment")
        return ''
    try:
        doc   = _docx.Document(io.BytesIO(payload))
        lines = [para.text for para in doc.paragraphs if para.text.strip()]
        return '\n'.join(lines).strip()
    except Exception as e:
        print(f"DOCX extraction failed: {e}")
        return ''


def _extract_txt(payload: bytes) -> str:
    """Decode a plain-text attachment, trying UTF-8 then latin-1."""
    for enc in ('utf-8', 'latin-1', 'cp1252'):
        try:
            return payload.decode(enc).strip()
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode('ascii', errors='replace').strip()


# ── Document category classification ──────────────────────────────────────────

# Keyword rules checked against lowercased filename + text.
# Order matters: more specific rules first.
_CATEGORY_RULES: List[Tuple[str, List[str]]] = [
    ('preauth_form',          ['pre-authorisation', 'pre-auth', 'preauth', 'pa-', 'pre auth']),
    ('gp_referral_letter',    ['referral letter', 'referral for', 'gp referral', 'refer to']),
    ('discharge_summary',     ['discharge summary', 'discharge date', 'discharged from']),
    ('bank_proof',            ['bank proof', 'iban', 'bank statement', 'account holder']),
    ('claim_form',            ['claim form', 'clm-', 'claim reference', 'amount claimed']),
    ('id_document',           ['passport', 'driving licence', 'driving license', 'id document',
                                'national id', 'date of birth', 'doc p', 'expiry date']),
    ('renewal_notice',        ['renewal notice', 'renewal date', 'new premium', 'old premium']),
    ('membership_certificate',['membership certificate', 'member certificate', 'plan name']),
    ('complaint_letter',      ['complaint', 'formal complaint', 'dissatisfied']),
    ('consultant_receipt',    ['consultant', 'specialist', 'outpatient receipt']),
    ('physiotherapy_invoice', ['physiotherapy', 'physio']),
    ('optical_receipt',       ['optical', 'optician', 'glasses', 'contact lens']),
    ('dental_invoice',        ['dental', 'dentist', 'tooth', 'teeth']),
    ('medical_invoice',       ['invoice', 'receipt', 'medical', 'treatment']),
]


def _classify_doc_category(filename: str, raw_text: str) -> str:
    """
    Classify an attachment into one of the 14 doc_category values.

    Checks keyword rules against the combined lowercased filename + extracted
    text.  Falls back to 'medical_invoice' (most generic) if no rule matches.
    """
    haystack = (filename + ' ' + raw_text).lower()

    for category, keywords in _CATEGORY_RULES:
        if any(kw in haystack for kw in keywords):
            return category

    return 'medical_invoice'   # safe default


# ── Structured field extraction ────────────────────────────────────────────────
#
# Each handler receives the raw extracted text and returns a dict whose keys
# match the structured_gold_fields for that doc_category in attachment_content.jsonl.
# Regex patterns mirror the patterns seen in the raw_text column of the dataset.

def _extract_structured_fields(doc_category: str, raw_text: str) -> Dict[str, Any]:
    """Dispatch to the appropriate extractor for the given doc_category."""
    _handlers = {
        'bank_proof':             _fields_bank_proof,
        'claim_form':             _fields_claim_form,
        'consultant_receipt':     _fields_invoice,
        'dental_invoice':         _fields_invoice,
        'medical_invoice':        _fields_invoice,
        'optical_receipt':        _fields_invoice,
        'physiotherapy_invoice':  _fields_invoice,
        'id_document':            _fields_id_document,
        'preauth_form':           _fields_preauth_form,
        'gp_referral_letter':     _fields_gp_referral,
        'discharge_summary':      _fields_discharge_summary,
        'renewal_notice':         _fields_renewal_notice,
        'membership_certificate': _fields_membership_certificate,
        'complaint_letter':       _fields_complaint_letter,
    }
    handler = _handlers.get(doc_category, _fields_invoice)
    return handler(raw_text)


# ── Per-category extractors ────────────────────────────────────────────────────

def _fields_bank_proof(text: str) -> Dict[str, Any]:
    """
    Keys: bank_name, iban_masked, account_holder
    Example raw_text: "Bank proof account holder Roisin Byrne IBAN ending 9902"
    """
    return {
        'bank_name':      _re_first(r'(?:bank of ireland|permanent tsb|aib|ulster bank|boa|tsb|credit union|revolut|n26|[a-z]+ bank)', text, ''),
        'iban_masked':    _re_first(r'(?:IE[*\d ]{14,22}|IBAN[:\s]+([A-Z0-9*\s]{10,25}))', text, ''),
        'account_holder': _re_first(r'account holder\s+([A-Z][a-z]+(?: [A-Z][a-z\']+)+)', text, ''),
    }


def _fields_claim_form(text: str) -> Dict[str, Any]:
    """
    Keys: claim_reference, policy_number, member_name, treatment_type, amount_claimed
    Example: "Claim form CLM-179023 Policy POL-IE-805483 Member Lorcan Murphy
              Treatment Pain relief medication Amount 817.75"
    """
    return {
        'claim_reference': _re_first(r'(CLM-\d+)',                                  text, ''),
        'policy_number':   _re_first(r'(POL-IE-\d{6})',                             text, '', re.IGNORECASE),
        'member_name':     _re_first(r'member\s+([A-Z][a-z]+(?: [A-Z][a-z\']+)+)', text, ''),
        'treatment_type':  _re_first(r'treatment\s+(.+?)(?:\s+amount|\s*$)',         text, ''),
        'amount_claimed':  _re_float(r'(?:amount|EUR|€)\s*([\d,]+\.?\d*)',           text),
    }


def _fields_invoice(text: str) -> Dict[str, Any]:
    """
    Shared extractor for: consultant_receipt, dental_invoice, medical_invoice,
    optical_receipt, physiotherapy_invoice.

    Keys: provider_name, provider_type, invoice_number, invoice_date,
          treatment_date, patient_name, member_id, treatment_type,
          diagnosis_text, amount, currency, tax_amount, receipt_present
    """
    # Infer provider_type from text keywords
    provider_type = 'general'
    lower = text.lower()
    if 'physio'             in lower: provider_type = 'physiotherapy'
    elif 'dental' in lower or 'dentist' in lower: provider_type = 'dental'
    elif 'optical' in lower or 'optician' in lower: provider_type = 'optical'
    elif 'consultant' in lower: provider_type = 'consultant'
    elif 'gp' in lower or 'general practitioner' in lower: provider_type = 'gp'

    raw_amount = _re_float(r'(?:amount|EUR|€)\s*([\d,]+\.?\d*)', text)

    return {
        'provider_name':   _re_first(r'^([A-Z][A-Za-z\s&]+(?:Clinic|Hospital|Centre|Center|Practice|Surgery))',
                                     text, '', re.MULTILINE),
        'provider_type':   provider_type,
        'invoice_number':  _re_first(r'(?:INV|Invoice)[- #]?(\w+\d+)',  text, ''),
        'invoice_date':    _re_first(r'(?:date|Date)\s+(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})',
                                     text, ''),
        'treatment_date':  _re_first(r'(?:treatment date|Date)\s+(\d{4}-\d{2}-\d{2})',
                                     text, ''),
        'patient_name':    _re_first(r'(?:patient|Patient)\s+([A-Z][a-z]+(?: [A-Z][a-z\']+)+)',
                                     text, ''),
        'member_id':       _re_first(r'(MEM-\d{6})',                    text, '', re.IGNORECASE),
        'treatment_type':  _re_first(r'(?:treatment|Treatment)\s+(.+?)(?:\s+amount|\s*$|\n)',
                                     text, ''),
        'diagnosis_text':  _re_first(r'(?:diagnosis|Diagnosis)[:\s]+(.+?)(?:\n|$)',
                                     text, ''),
        'amount':          raw_amount,
        'currency':        'EUR' if 'eur' in lower or '€' in text else
                           'GBP' if 'gbp' in lower or '£' in text else 'EUR',
        'tax_amount':      _re_float(r'(?:tax|VAT|vat)\s*([\d,]+\.?\d*)', text),
        'receipt_present': bool(re.search(r'\b(?:receipt|invoice|paid)\b', text, re.I)),
    }


def _fields_id_document(text: str) -> Dict[str, Any]:
    """
    Keys: document_type, full_name, date_of_birth, document_number,
          expiry_date, address_present
    Example: "passport Eoin Murphy DOB 1981-06-20 Doc P5789153"
    """
    lower = text.lower()
    if 'passport'       in lower: doc_type = 'passport'
    elif 'driving'      in lower: doc_type = 'driving_licence'
    elif 'national'     in lower: doc_type = 'national_id'
    else:                          doc_type = 'id_document'

    return {
        'document_type':   doc_type,
        'full_name':       _re_first(r'(?:passport|licence|id)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z\']+)+)',
                                     text, ''),
        'date_of_birth':   _re_first(r'(?:DOB|date of birth|born)[:\s]+(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})',
                                     text, '', re.I),
        'document_number': _re_first(r'(?:Doc|No|Number|#)[:\s]*([A-Z0-9]{6,12})',
                                     text, '', re.I),
        'expiry_date':     _re_first(r'(?:expiry|expires|valid until)[:\s]+(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4})',
                                     text, '', re.I),
        'address_present': bool(re.search(r'\b\d+\s+[A-Z][a-z]+\s+(?:Street|Road|Avenue|Lane|Close|Drive|Way)\b', text)),
    }


def _fields_preauth_form(text: str) -> Dict[str, Any]:
    """
    Keys: form_id, patient_name, consultant_name, hospital_name,
          proposed_treatment, treatment_date, estimated_cost,
          diagnosis_text, urgency_level
    Example: "Pre-authorisation form PA-88492 Patient Saoirse Moore
              Consultant Dr Byrne Hospital Blackrock Clinic Treatment Diagnostic scan"
    """
    lower = text.lower()
    if   'urgent'   in lower: urgency = 'urgent'
    elif 'elective' in lower: urgency = 'elective'
    else:                      urgency = 'routine'

    return {
        'form_id':            _re_first(r'(PA-\d+)',                                          text, ''),
        'patient_name':       _re_first(r'patient\s+([A-Z][a-z]+(?: [A-Z][a-z\']+)+)',       text, '', re.I),
        'consultant_name':    _re_first(r'consultant\s+(Dr\.?\s+[A-Za-z\']+)',                text, '', re.I),
        'hospital_name':      _re_first(r'hospital\s+([A-Z][A-Za-z\s]+?)(?:\s+treatment|\s*$|\n)',
                                        text, '', re.I),
        'proposed_treatment': _re_first(r'treatment\s+(.+?)(?:\s*$|\n)',                      text, '', re.I),
        'treatment_date':     _re_first(r'(?:treatment date|date)[:\s]+(\d{4}-\d{2}-\d{2})', text, '', re.I),
        'estimated_cost':     _re_float(r'(?:cost|amount|EUR|€)\s*([\d,]+\.?\d*)',            text),
        'diagnosis_text':     _re_first(r'(?:diagnosis|reason)[:\s]+(.+?)(?:\n|$)',           text, '', re.I),
        'urgency_level':      urgency,
    }


def _fields_gp_referral(text: str) -> Dict[str, Any]:
    """
    Keys: referrer_name, patient_name, referral_reason, referral_date
    Example: "Referral letter for Saoirse Moore reason Diagnostic scan date 2025-02-21"
    """
    return {
        'referrer_name':   _re_first(r'(?:from|Dr\.?\s+|referred by\s+)(Dr\.?\s*[A-Za-z\']+)',
                                     text, '', re.I),
        'patient_name':    _re_first(r'(?:for|patient)\s+([A-Z][a-z]+(?: [A-Z][a-z\']+)+)',
                                     text, '', re.I),
        'referral_reason': _re_first(r'reason\s+(.+?)(?:\s+date|\s*$|\n)',                text, '', re.I),
        'referral_date':   _re_first(r'(?:date|referral date)[:\s]+(\d{4}-\d{2}-\d{2})',  text, '', re.I),
    }


def _fields_discharge_summary(text: str) -> Dict[str, Any]:
    """
    Keys: patient_name, hospital_name, discharge_date
    Example: "Discharge summary patient Eoin Fitzgerald hospital Bon Secours Cork
              discharge 2026-01-28"
    """
    return {
        'patient_name':  _re_first(r'patient\s+([A-Z][a-z]+(?: [A-Z][a-z\']+)+)', text, '', re.I),
        'hospital_name': _re_first(r'hospital\s+([A-Z][A-Za-z\s]+?)(?:\s+discharge|\s*$|\n)',
                                   text, '', re.I),
        'discharge_date': _re_first(r'discharge(?:d| date)?[:\s]+(\d{4}-\d{2}-\d{2})',
                                    text, '', re.I),
    }


def _fields_renewal_notice(text: str) -> Dict[str, Any]:
    """
    Keys: renewal_year, old_premium, new_premium, renewal_date, plan_name, member_count
    Example: "Renewal Notice Plan Select Hospital Old premium EUR 1616.62
              New premium EUR 1739.64 Renewal date 2025-05-08"
    """
    renewal_date = _re_first(r'renewal date\s+(\d{4}-\d{2}-\d{2})', text, '', re.I)
    renewal_year = int(renewal_date[:4]) if renewal_date and len(renewal_date) >= 4 else None

    return {
        'renewal_year':  renewal_year,
        'old_premium':   _re_float(r'old premium\s+(?:EUR|€)?\s*([\d,]+\.?\d*)',  text),
        'new_premium':   _re_float(r'new premium\s+(?:EUR|€)?\s*([\d,]+\.?\d*)',  text),
        'renewal_date':  renewal_date,
        'plan_name':     _re_first(r'plan\s+([A-Z][A-Za-z\s]+?)(?:\s+old|\s+new|\s*$|\n)',
                                   text, '', re.I),
        'member_count':  _re_int(r'member(?:s| count)[:\s]+(\d+)', text),
    }


def _fields_membership_certificate(text: str) -> Dict[str, Any]:
    """
    Keys: plan_name, member_name, policy_number
    Example: "Membership certificate plan HealthWise Gold member Emma Murphy
              policy POL-IE-479821"
    """
    return {
        'plan_name':      _re_first(r'plan\s+([A-Z][A-Za-z\s]+?)(?:\s+member|\s*$|\n)', text, '', re.I),
        'member_name':    _re_first(r'member\s+([A-Z][a-z]+(?: [A-Z][a-z\']+)+)',       text, '', re.I),
        'policy_number':  _re_first(r'(POL-IE-\d{6})',                                  text, '', re.I),
    }


def _fields_complaint_letter(text: str) -> Dict[str, Any]:
    """
    Keys: complaint_topic, member_name
    Example: "Complaint letter from Tadhg Brennan regarding renewal pricing"
    """
    return {
        'complaint_topic': _re_first(r'regarding\s+(.+?)(?:\s*$|\n|\.|,)', text, '', re.I),
        'member_name':     _re_first(r'(?:from|by)\s+([A-Z][a-z]+(?: [A-Z][a-z\']+)+)', text, '', re.I),
    }


# ── Regex helper utilities ─────────────────────────────────────────────────────

def _re_first(
    pattern: str,
    text: str,
    default: str = '',
    flags: int = 0,
) -> str:
    """Return the first capturing group (or full match) or default."""
    m = re.search(pattern, text, flags)
    if not m:
        return default
    return (m.group(1) if m.lastindex else m.group(0)).strip()


def _re_float(pattern: str, text: str) -> Optional[float]:
    """Extract the first float from the first match, or None."""
    m = re.search(pattern, text, re.I)
    if not m:
        return None
    raw = (m.group(1) if m.lastindex else m.group(0)).replace(',', '')
    try:
        return float(raw)
    except (ValueError, AttributeError):
        return None


def _re_int(pattern: str, text: str) -> Optional[int]:
    """Extract the first integer from the first match, or None."""
    val = _re_float(pattern, text)
    return int(val) if val is not None else None


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
    """Return (count, has_attachment) — preserved for backward compatibility."""
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
