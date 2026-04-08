"""
Email Sender Lambda Function
Sends auto-response emails via Amazon SES.

Attachments: knowledge base source files referenced in the response are fetched
from S3 and attached. Citation markers [1], [2] in the response body become
<cid:> hyperlinks pointing to the corresponding attached file.
"""
import html as _html
import json
import mimetypes
import os
import re as _re
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# ── AWS clients ───────────────────────────────────────────────────────────────
ses_client     = boto3.client('ses')
dynamodb       = boto3.resource('dynamodb')
s3_client      = boto3.client('s3')

# ── Environment variables ─────────────────────────────────────────────────────
EMAIL_TABLE_NAME      = os.environ['EMAIL_TABLE_NAME']
SENDER_EMAIL          = os.environ['SENDER_EMAIL']
SENDER_NAME           = os.environ.get('SENDER_NAME', 'Laya Healthcare Support')
KNOWLEDGE_BASE_BUCKET = os.environ.get('KNOWLEDGE_BASE_BUCKET', '')
EMBEDDINGS_TABLE_NAME = os.environ.get('EMBEDDINGS_TABLE_NAME', '')

# SES 10 MB raw message limit — keep a safety margin
MAX_ATTACHMENT_BYTES  = 8 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 4 * 1024 * 1024

email_table      = dynamodb.Table(EMAIL_TABLE_NAME)
embeddings_table = dynamodb.Table(EMBEDDINGS_TABLE_NAME) if EMBEDDINGS_TABLE_NAME else None

# Matches [1], [2], … citation markers in plain text
_CITATION_RE = _re.compile(r'\[(\d+)\]')


# ── Lambda handler ─────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Send an AI-generated email response via SES.
    RAG source files are attached; [N] citations in the body become cid: hyperlinks.
    """
    try:
        print(f"Event: {json.dumps(event)}")

        email_id      = event.get('email_id')
        recipient     = event.get('recipient_email')
        original_subj = event.get('subject', 'Your Inquiry')
        response_text = event.get('response_text', '')
        confidence    = float(event.get('confidence_score', 0))
        reference_ids = list(event.get('reference_ids') or [])

        if not recipient or not response_text:
            raise ValueError("Missing required fields: recipient_email or response_text")

        subject = f"Re: {original_subj}"

        # Resolve attachments and the citation → cid mapping
        attachments, citation_to_attachment = _resolve_attachments(reference_ids)

        body_html = _build_html_body(response_text, confidence, citation_to_attachment)
        body_text = response_text   # plain text keeps [1], [2] as-is

        if attachments:
            message_id = _send_with_attachments(
                recipient, subject, body_text, body_html, attachments
            )
        else:
            message_id = _send_simple(recipient, subject, body_text, body_html)

        print(f"Email sent: {message_id}  attachments={len(attachments)}")

        if email_id:
            email_table.update_item(
                Key={'email_id': email_id},
                UpdateExpression=(
                    'SET email_sent = :sent, email_message_id = :mid, '
                    'email_sent_timestamp = :ts, attachment_count = :ac'
                ),
                ExpressionAttributeValues={
                    ':sent': True,
                    ':mid':  message_id,
                    ':ts':   datetime.utcnow().isoformat() + 'Z',
                    ':ac':   len(attachments),
                },
            )

        return {
            'statusCode':       200,
            'email_sent':       True,
            'message_id':       message_id,
            'recipient':        recipient,
            'attachments_sent': len(attachments),
        }

    except ClientError as e:
        code = e.response['Error']['Code']
        print(f"SES Error: {code} — {e}")
        return {'statusCode': 500, 'email_sent': False, 'error': str(e)}

    except Exception as e:
        print(f"Error sending email: {e}")
        return {'statusCode': 500, 'email_sent': False, 'error': str(e)}


# ── Attachment resolution ──────────────────────────────────────────────────────

def _resolve_attachments(
    reference_ids: List[str],
) -> Tuple[List[Tuple[str, bytes, str, str]], Dict[int, Tuple[str, str]]]:
    """
    Given an ordered list of doc_ids (citation [1] = index 0, [2] = index 1, …):
      1. Look up source_key for each doc_id via the DynamoDB embeddings table.
      2. Deduplicate source files (multiple chunks from the same file share one attachment).
      3. Download files from S3, assign Content-IDs.
      4. Return:
           attachments       : [(filename, file_bytes, content_type, cid), …]
           citation_to_attach: {citation_number: (human_title, cid), …}
    """
    if not reference_ids or not KNOWLEDGE_BASE_BUCKET or not embeddings_table:
        return [], {}

    # ── Step 1: resolve source_key per doc_id, preserve citation order ─────────
    # citation_sources[i] = (citation_num, source_key, title) or None
    citation_sources: List[Optional[Tuple[int, str, str]]] = []
    for i, doc_id in enumerate(reference_ids, start=1):
        source_key = _get_source_key(doc_id)
        if source_key:
            title = _source_key_to_title(source_key)
            citation_sources.append((i, source_key, title))
        else:
            citation_sources.append(None)

    # ── Step 2: deduplicate source files (keep insertion order) ────────────────
    unique_sources: Dict[str, str] = {}   # source_key → title
    for entry in citation_sources:
        if entry and entry[1] not in unique_sources:
            unique_sources[entry[1]] = entry[2]

    # ── Step 3: download files, assign CIDs ────────────────────────────────────
    source_key_to_cid: Dict[str, str] = {}
    attachments: List[Tuple[str, bytes, str, str]] = []
    total_bytes = 0
    attach_num  = 1

    for source_key, title in unique_sources.items():
        if total_bytes >= MAX_ATTACHMENT_BYTES:
            print(f"Attachment budget exhausted — skipping {source_key}")
            break
        file_bytes = _download_from_s3(source_key)
        if file_bytes is None:
            continue
        if len(file_bytes) > MAX_SINGLE_FILE_BYTES:
            print(f"File {source_key} too large ({len(file_bytes)} B) — skipping")
            continue
        if total_bytes + len(file_bytes) > MAX_ATTACHMENT_BYTES:
            print(f"Adding {source_key} would exceed budget — skipping")
            break
        filename     = os.path.basename(source_key)
        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        cid          = f"kb-attachment-{attach_num}"
        source_key_to_cid[source_key] = cid
        attachments.append((filename, file_bytes, content_type, cid))
        total_bytes += len(file_bytes)
        print(f"Attaching [{attach_num}] {filename}  ({len(file_bytes)} B)  cid={cid}")
        attach_num += 1

    # ── Step 4: build citation → (title, cid) map ──────────────────────────────
    citation_to_attachment: Dict[int, Tuple[str, str]] = {}
    for entry in citation_sources:
        if entry is None:
            continue
        citation_num, source_key, title = entry
        if source_key in source_key_to_cid:
            citation_to_attachment[citation_num] = (title, source_key_to_cid[source_key])

    return attachments, citation_to_attachment


def _get_source_key(doc_id: str) -> Optional[str]:
    """Look up doc_id in the embeddings table and return metadata.source_key."""
    try:
        resp = embeddings_table.get_item(
            Key={'doc_id': doc_id},
            ProjectionExpression='metadata',
        )
        item = resp.get('Item')
        if item and isinstance(item.get('metadata'), dict):
            return item['metadata'].get('source_key')
    except Exception as e:
        print(f"Could not resolve source_key for {doc_id}: {e}")
    return None


def _download_from_s3(source_key: str) -> Optional[bytes]:
    """Download file bytes from the knowledge base S3 bucket."""
    try:
        resp = s3_client.get_object(Bucket=KNOWLEDGE_BASE_BUCKET, Key=source_key)
        return resp['Body'].read()
    except Exception as e:
        print(f"Could not download s3://{KNOWLEDGE_BASE_BUCKET}/{source_key}: {e}")
        return None


def _source_key_to_title(source_key: str) -> str:
    """Derive a clean human-readable title from an S3 source_key."""
    name = source_key.split('/')[-1]
    name = _re.sub(r'\.[a-z]{2,4}$', '', name)
    name = _re.sub(r'_\d+$', '', name)
    name = _re.sub(r'^knowledge_base_?', '', name, flags=_re.IGNORECASE)
    name = name.replace('_', ' ').replace('-', ' ').strip()
    return ' '.join(w.capitalize() for w in name.split()) or 'Laya Healthcare Policy Guide'


# ── SES send helpers ───────────────────────────────────────────────────────────

def _send_simple(
    recipient: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> str:
    resp = ses_client.send_email(
        Source=f"{SENDER_NAME} <{SENDER_EMAIL}>",
        Destination={'ToAddresses': [recipient]},
        Message={
            'Subject': {'Data': subject, 'Charset': 'UTF-8'},
            'Body': {
                'Text': {'Data': body_text, 'Charset': 'UTF-8'},
                'Html': {'Data': body_html,  'Charset': 'UTF-8'},
            },
        },
    )
    return resp['MessageId']


def _send_with_attachments(
    recipient: str,
    subject: str,
    body_text: str,
    body_html: str,
    attachments: List[Tuple[str, bytes, str, str]],
) -> str:
    """Send email with MIME attachments. Each attachment carries a Content-ID header."""
    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From']    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg['To']      = recipient

    # Inline body (text + HTML alternative)
    body_part = MIMEMultipart('alternative')
    body_part.attach(MIMEText(body_text, 'plain', 'utf-8'))
    body_part.attach(MIMEText(body_html,  'html',  'utf-8'))
    msg.attach(body_part)

    # Attachments with Content-ID for cid: link resolution
    for filename, file_bytes, content_type, cid in attachments:
        maintype, subtype = content_type.split('/', 1)
        if maintype == 'text':
            part = MIMEText(file_bytes.decode('utf-8', errors='replace'), subtype, 'utf-8')
        else:
            part = MIMEApplication(file_bytes, subtype)
        part.add_header('Content-Disposition', 'attachment', filename=filename)
        part.add_header('Content-ID', f'<{cid}>')
        msg.attach(part)

    resp = ses_client.send_raw_email(
        Source=f"{SENDER_NAME} <{SENDER_EMAIL}>",
        Destinations=[recipient],
        RawMessage={'Data': msg.as_bytes()},
    )
    return resp['MessageId']


# ── HTML body builder ──────────────────────────────────────────────────────────

def _build_html_body(
    response_text: str,
    confidence_score: float,
    citation_to_attachment: Dict[int, Tuple[str, str]],
) -> str:
    """
    Build the HTML email body.
    - Converts plain-text [N] citation markers to superscript cid: hyperlinks.
    - Appends a footnote bar listing cited documents with their attachment links.
    """
    confidence_colour = '28a745' if confidence_score >= 0.8 else 'ffc107'

    # HTML-escape the response text first, then convert line breaks, then inject citations
    escaped = _html.escape(response_text)
    escaped = escaped.replace('\n', '<br>\n')

    def _replace_citation(match: _re.Match) -> str:
        num = int(match.group(1))
        if num in citation_to_attachment:
            title, cid = citation_to_attachment[num]
            return (
                f'<sup><a href="cid:{cid}" title="{_html.escape(title)}" '
                f'style="color:#003366;text-decoration:none;font-weight:bold;">[{num}]</a></sup>'
            )
        return match.group(0)   # leave unchanged if no mapping

    body_html = _CITATION_RE.sub(_replace_citation, escaped)

    # Build footnote section
    footnotes_html = ''
    if citation_to_attachment:
        # Deduplicate by cid (multiple citations may share one attachment)
        seen_cids: set = set()
        footnote_items = []
        for num in sorted(citation_to_attachment):
            title, cid = citation_to_attachment[num]
            if cid not in seen_cids:
                seen_cids.add(cid)
                footnote_items.append(
                    f'<span style="margin-right:1.5em;">'
                    f'<a href="cid:{cid}" style="color:#003366;text-decoration:none;">'
                    f'[{num}] {_html.escape(title)}</a>'
                    f'</span>'
                )
        if footnote_items:
            footnotes_html = f"""
  <div style="margin-top:24px;padding-top:12px;border-top:1px solid #dee2e6;
              font-size:11px;color:#555;line-height:1.8;">
    <strong>Attached references:</strong><br>
    {''.join(footnote_items)}
  </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <style>
    body {{ font-family: Arial, sans-serif; line-height: 1.7; color: #333; margin: 0; padding: 0; }}
    .container {{ max-width: 620px; margin: 0 auto; padding: 24px; }}
    .header {{ background-color: #003366; color: white; padding: 20px 24px;
               border-radius: 6px 6px 0 0; }}
    .header h2 {{ margin: 0; font-size: 18px; font-weight: 600; }}
    .content {{ background-color: #ffffff; padding: 24px;
                border: 1px solid #dee2e6; border-top: none; }}
    .footer {{ background-color: #f8f9fa; padding: 14px 24px; text-align: center;
               font-size: 11px; color: #6c757d; border: 1px solid #dee2e6;
               border-top: none; border-radius: 0 0 6px 6px; }}
    .confidence {{ background-color: #{confidence_colour}; color: white;
                   padding: 3px 10px; border-radius: 3px; font-size: 11px; }}
    sup a {{ color: #003366; text-decoration: none; font-weight: bold; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header"><h2>Laya Healthcare</h2></div>
    <div class="content">
      {body_html}
      {footnotes_html}
    </div>
    <div class="footer">
      <span class="confidence">AI Confidence: {confidence_score:.0%}</span>
      <p style="margin:8px 0 0;">This is an automated response. Reply to this email for further assistance.</p>
    </div>
  </div>
</body>
</html>"""
