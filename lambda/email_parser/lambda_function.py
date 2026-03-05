"""
Email Parser Lambda Function
Parses raw emails from S3 and extracts core fields
"""
import json
import os
import uuid
from datetime import datetime
from email import message_from_string
from email.utils import parseaddr
from typing import Dict, Any
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']
email_table = dynamodb.Table(EMAIL_TABLE_NAME)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for email parsing

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
            if 's3' in record:
                # Standard S3 event trigger
                bucket = record['s3']['bucket']['name']
                key = record['s3']['object']['key']
            elif 'Sns' in record:
                # SNS notification (SES or Gmail IMAP via SNS)
                sns_message = json.loads(record['Sns']['Message'])
                action = sns_message.get('receipt', {}).get('action', {})
                bucket = action.get('bucketName')
                key = action.get('objectKey')
            else:
                raise ValueError(f"Unsupported Records event source: {record.get('eventSource', 'unknown')}")
        else:
            # Direct invocation with bucket/key
            bucket = event.get('bucket')
            key = event.get('key')

        if not bucket or not key:
            raise ValueError("Missing bucket or key in event")

        # Get email from S3
        print(f"Fetching email from s3://{bucket}/{key}")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        raw_email = response['Body'].read().decode('utf-8')

        # Parse email
        parsed_data = parse_email(raw_email)

        # Generate unique email_id
        email_id = str(uuid.uuid4())

        # Add metadata
        parsed_data.update({
            'email_id': email_id,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            's3_bucket': bucket,
            's3_key': key,
            'processing_status': 'parsed',
            'confidence_level': 'pending'
        })

        # Store in DynamoDB
        email_table.put_item(Item=parsed_data)
        print(f"Stored email {email_id} in DynamoDB")

        return {
            'statusCode': 200,
            'email_id': email_id,
            'parsed_data': parsed_data
        }

    except ClientError as e:
        print(f"AWS Error: {str(e)}")
        raise
    except Exception as e:
        print(f"Error: {str(e)}")
        raise


def parse_email(raw_email: str) -> Dict[str, Any]:
    """
    Parse raw email text and extract fields

    Args:
        raw_email: Raw email text

    Returns:
        Dict with parsed email fields
    """
    try:
        # Parse email using Python's email library
        msg = message_from_string(raw_email)

        # Extract fields — parseaddr strips display name e.g. "Name <email>" → "email"
        _, from_address = parseaddr(msg.get('From', ''))
        _, to_address = parseaddr(msg.get('To', ''))
        subject = msg.get('Subject', '')
        date = msg.get('Date', '')

        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
        else:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')

        # Basic email validation
        if not from_address or not body:
            raise ValueError("Invalid email: missing required fields")

        # Store original addresses (needed for sending replies)
        # PII redaction is applied only in logs, not in stored data
        print(f"Parsed email from: {redact_pii(from_address)} to: {redact_pii(to_address)}")
        return {
            'from_address': from_address,
            'to_address': to_address,
            'subject': subject,
            'date': date,
            'body': body,
            'body_length': len(body)
        }

    except Exception as e:
        print(f"Error parsing email: {str(e)}")
        raise


def redact_pii(text: str) -> str:
    """
    Redact PII from text (basic implementation)
    In production, use more sophisticated PII detection

    Args:
        text: Input text

    Returns:
        Text with redacted PII
    """
    # For logging purposes, redact email addresses
    import re
    # Keep first 3 chars and domain, redact middle
    redacted = re.sub(r'(\w{1,3})\w+@', r'\1***@', text)
    return redacted
