"""
Gmail IMAP Poller Lambda Function
Polls Gmail inbox via IMAP, fetches unread emails, and triggers processing workflow.
"""

import imaplib
import email
import json
import os
import uuid
import boto3
from datetime import datetime
from email.utils import parseaddr

# Initialize AWS clients
s3_client = boto3.client('s3')
stepfunctions_client = boto3.client('stepfunctions')

# Environment variables
GMAIL_ADDRESS = os.environ['GMAIL_ADDRESS']
GMAIL_APP_PASSWORD = os.environ['GMAIL_APP_PASSWORD']
S3_BUCKET = os.environ['S3_BUCKET']
STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']
IMAP_SERVER = os.environ.get('IMAP_SERVER', 'imap.gmail.com')
MARK_AS_READ = os.environ.get('MARK_AS_READ', 'true').lower() == 'true'


def lambda_handler(event, context):
    """
    Main handler - polls Gmail via IMAP and triggers workflow for new emails.
    """
    print(f"Starting Gmail IMAP polling for {GMAIL_ADDRESS}")

    emails_processed = 0
    errors = []

    try:
        # Connect to Gmail IMAP
        mail = connect_to_gmail()

        # Select inbox
        mail.select('inbox')

        # Search for unread emails
        status, message_ids = mail.search(None, 'UNSEEN')

        if status != 'OK':
            raise Exception(f"IMAP search failed: {status}")

        # Get list of email IDs
        email_ids = message_ids[0].split()

        print(f"Found {len(email_ids)} unread email(s)")

        # Process each email
        for email_id in email_ids:
            try:
                # Fetch email
                status, msg_data = mail.fetch(email_id, '(RFC822)')

                if status != 'OK':
                    print(f"Failed to fetch email ID {email_id}: {status}")
                    continue

                # Parse email
                raw_email = msg_data[0][1]
                email_message = email.message_from_bytes(raw_email)

                # Process email
                result = process_email(email_message, raw_email)

                if result['success']:
                    emails_processed += 1

                    # Mark as read if configured
                    if MARK_AS_READ:
                        mail.store(email_id, '+FLAGS', '\\Seen')
                        print(f"Marked email {email_id} as read")
                else:
                    errors.append({
                        'email_id': email_id.decode('utf-8'),
                        'error': result.get('error', 'Unknown error')
                    })

            except Exception as e:
                print(f"Error processing email ID {email_id}: {str(e)}")
                errors.append({
                    'email_id': email_id.decode('utf-8'),
                    'error': str(e)
                })

        # Close connection
        mail.close()
        mail.logout()

        print(f"✓ Successfully processed {emails_processed} email(s)")

        return {
            'statusCode': 200,
            'emails_processed': emails_processed,
            'errors': errors,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"✗ IMAP polling failed: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


def connect_to_gmail():
    """
    Connect to Gmail IMAP server.
    """
    try:
        # Connect with SSL
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)

        # Login
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)

        print(f"✓ Connected to Gmail IMAP as {GMAIL_ADDRESS}")
        return mail

    except imaplib.IMAP4.error as e:
        print(f"✗ IMAP authentication failed: {str(e)}")
        print("Make sure you're using an App Password, not your regular Gmail password")
        print("Generate one at: https://myaccount.google.com/apppasswords")
        raise

    except Exception as e:
        print(f"✗ IMAP connection failed: {str(e)}")
        raise


def process_email(email_message, raw_email):
    """
    Process a single email: upload to S3 and trigger Step Functions.
    """
    try:
        # Extract email metadata
        from_addr = parseaddr(email_message.get('From', ''))[1]
        to_addr = parseaddr(email_message.get('To', ''))[1]
        subject = decode_header_value(email_message.get('Subject', ''))
        date = email_message.get('Date', '')
        message_id = email_message.get('Message-ID', f'<{uuid.uuid4()}@gmail-imap>')

        # Extract body
        body = extract_email_body(email_message)

        # Generate unique ID
        email_id = str(uuid.uuid4())

        print(f"Processing email: From={from_addr}, Subject={subject}")

        # Upload raw email to S3
        s3_key = f"incoming/gmail-{email_id}.eml"
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=raw_email,
            ContentType='message/rfc822',
            Metadata={
                'from': from_addr,
                'to': to_addr,
                'subject': subject,
                'source': 'gmail-imap'
            }
        )

        print(f"✓ Uploaded to S3: {s3_key}")

        # Trigger Step Functions
        execution_name = f"gmail-{email_id}"

        # Create input matching SNS format (for compatibility)
        sf_input = {
            "Records": [{
                "eventSource": "gmail:imap",
                "Sns": {
                    "Message": json.dumps({
                        "notificationType": "Received",
                        "mail": {
                            "messageId": message_id,
                            "timestamp": datetime.utcnow().isoformat(),
                            "source": from_addr,
                            "destination": [to_addr]
                        },
                        "receipt": {
                            "action": {
                                "type": "S3",
                                "bucketName": S3_BUCKET,
                                "objectKey": s3_key
                            }
                        }
                    })
                }
            }]
        }

        response = stepfunctions_client.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=execution_name,
            input=json.dumps(sf_input)
        )

        print(f"✓ Triggered Step Functions: {response['executionArn']}")

        return {
            'success': True,
            'email_id': email_id,
            's3_key': s3_key,
            'execution_arn': response['executionArn']
        }

    except Exception as e:
        print(f"✗ Failed to process email: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def extract_email_body(email_message):
    """
    Extract plain text body from email message.
    """
    body = ""

    if email_message.is_multipart():
        for part in email_message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            # Get text/plain parts
            if content_type == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
                except:
                    pass
    else:
        try:
            body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
        except:
            body = str(email_message.get_payload())

    return body.strip()


def decode_header_value(header_value):
    """
    Decode email header value (handles encoded subjects).
    """
    if not header_value:
        return ""

    try:
        decoded_parts = email.header.decode_header(header_value)
        decoded_string = ""

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_string += part.decode(encoding or 'utf-8', errors='ignore')
            else:
                decoded_string += part

        return decoded_string
    except:
        return str(header_value)
