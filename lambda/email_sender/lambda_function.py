"""
Email Sender Lambda Function
Sends auto-response emails via Amazon SES
"""
import json
import os
import boto3
from typing import Dict, Any
from botocore.exceptions import ClientError

# Initialize AWS clients
ses_client = boto3.client('ses')
dynamodb = boto3.resource('dynamodb')

# Environment variables
EMAIL_TABLE_NAME = os.environ['EMAIL_TABLE_NAME']
SENDER_EMAIL = os.environ['SENDER_EMAIL']
SENDER_NAME = os.environ.get('SENDER_NAME', 'InsureMail AI Support')

email_table = dynamodb.Table(EMAIL_TABLE_NAME)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for sending emails

    Args:
        event: Input with email_id, recipient, subject, body, response_text
        context: Lambda context

    Returns:
        Dict with send status
    """
    try:
        print(f"Event: {json.dumps(event)}")

        # Extract required fields
        email_id = event.get('email_id')
        recipient = event.get('recipient_email')
        original_subject = event.get('subject', 'Your Inquiry')
        response_text = event.get('response_text', '')
        confidence_score = event.get('confidence_score', 0)

        if not recipient or not response_text:
            raise ValueError("Missing required fields: recipient_email or response_text")

        # Build email subject (Re: Original Subject)
        subject = f"Re: {original_subject}"

        # Build email body
        body_html = build_email_body(response_text, confidence_score)
        body_text = response_text

        # Send email via SES
        send_response = ses_client.send_email(
            Source=SENDER_EMAIL,
            Destination={
                'ToAddresses': [recipient]
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': body_text,
                        'Charset': 'UTF-8'
                    },
                    'Html': {
                        'Data': body_html,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )

        message_id = send_response['MessageId']
        print(f"Email sent successfully: {message_id}")

        # Update email record in DynamoDB
        if email_id:
            email_table.update_item(
                Key={'email_id': email_id},
                UpdateExpression='SET email_sent = :sent, email_message_id = :mid, email_sent_timestamp = :ts',
                ExpressionAttributeValues={
                    ':sent': True,
                    ':mid': message_id,
                    ':ts': boto3.dynamodb.types.Decimal(str(context.get_remaining_time_in_millis()))
                }
            )

        return {
            'statusCode': 200,
            'email_sent': True,
            'message_id': message_id,
            'recipient': recipient
        }

    except ClientError as e:
        error_code = e.response['Error']['Code']
        print(f"SES Error: {error_code} - {str(e)}")

        if error_code == 'MessageRejected':
            print("Email was rejected. Check SES sending limits and recipient verification.")
        elif error_code == 'MailFromDomainNotVerifiedException':
            print("Sender email domain not verified in SES.")

        return {
            'statusCode': 500,
            'email_sent': False,
            'error': str(e)
        }

    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return {
            'statusCode': 500,
            'email_sent': False,
            'error': str(e)
        }


def build_email_body(response_text: str, confidence_score: float) -> str:
    """
    Build HTML email body

    Args:
        response_text: AI-generated response
        confidence_score: Confidence score (0-1)

    Returns:
        HTML formatted email body
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .header {{
                background-color: #667eea;
                color: white;
                padding: 20px;
                text-align: center;
                border-radius: 5px 5px 0 0;
            }}
            .content {{
                background-color: #f9f9f9;
                padding: 20px;
                border: 1px solid #ddd;
            }}
            .footer {{
                background-color: #f1f1f1;
                padding: 15px;
                text-align: center;
                font-size: 12px;
                color: #666;
                border-radius: 0 0 5px 5px;
            }}
            .confidence {{
                background-color: #{'28a745' if confidence_score >= 0.8 else 'ffc107'};
                color: white;
                padding: 5px 10px;
                border-radius: 3px;
                display: inline-block;
                font-size: 11px;
                margin-top: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>InsureMail AI Support</h2>
            </div>
            <div class="content">
                <p>{response_text.replace(chr(10), '<br>')}</p>
                <div class="confidence">
                    Confidence: {confidence_score:.0%}
                </div>
            </div>
            <div class="footer">
                <p>This is an automated response powered by AI.</p>
                <p>If you need further assistance, please reply to this email.</p>
                <p>&copy; 2026 InsureMail AI. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
