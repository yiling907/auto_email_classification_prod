"""
Email Receiver Lambda Function
Processes SES notifications from SNS and triggers the email processing pipeline
"""
import json
import os
import boto3
from datetime import datetime
from typing import Dict, Any

# Initialize AWS clients
s3_client = boto3.client('s3')
sfn_client = boto3.client('stepfunctions')

# Environment variables
STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']
EMAIL_BUCKET_NAME = os.environ['EMAIL_BUCKET_NAME']


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for SES email notifications

    Args:
        event: SNS event containing SES notification
        context: Lambda context

    Returns:
        Dict with processing status
    """
    try:
        print(f"Received event: {json.dumps(event)}")

        # Parse SNS message
        for record in event.get('Records', []):
            if record.get('EventSource') == 'aws:sns':
                # Parse SES notification
                message = json.loads(record['Sns']['Message'])

                if message.get('notificationType') == 'Received':
                    # Process received email
                    process_email(message)

        return {
            'statusCode': 200,
            'body': json.dumps('Email processed successfully')
        }

    except Exception as e:
        print(f"Error processing email: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error: {str(e)}')
        }


def process_email(ses_message: Dict[str, Any]) -> None:
    """
    Process SES email notification and trigger Step Functions

    Args:
        ses_message: SES notification message
    """
    try:
        mail = ses_message.get('mail', {})
        receipt = ses_message.get('receipt', {})

        # Extract S3 location
        s3_action = receipt.get('action', {})
        s3_bucket = s3_action.get('bucketName')
        s3_key = s3_action.get('objectKey')

        if not s3_bucket or not s3_key:
            print("Warning: No S3 location in SES message")
            return

        # Extract email metadata
        email_metadata = {
            'message_id': mail.get('messageId'),
            'timestamp': mail.get('timestamp'),
            'source': mail.get('source'),
            'destination': mail.get('destination', []),
            'subject': mail.get('commonHeaders', {}).get('subject', ''),
            'spam_verdict': receipt.get('spamVerdict', {}).get('status'),
            'virus_verdict': receipt.get('virusVerdict', {}).get('status'),
            'dkim_verdict': receipt.get('dkimVerdict', {}).get('status'),
            'spf_verdict': receipt.get('spfVerdict', {}).get('status')
        }

        print(f"Processing email: {email_metadata['message_id']}")
        print(f"S3 location: s3://{s3_bucket}/{s3_key}")

        # Trigger Step Functions workflow
        execution_input = {
            'bucket': s3_bucket,
            'key': s3_key,
            'metadata': email_metadata
        }

        response = sfn_client.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=f"email-{email_metadata['message_id']}-{int(datetime.now().timestamp())}",
            input=json.dumps(execution_input)
        )

        print(f"Started Step Functions execution: {response['executionArn']}")

    except Exception as e:
        print(f"Error in process_email: {str(e)}")
        raise
