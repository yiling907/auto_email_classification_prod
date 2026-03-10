"""
Unit tests for email_parser Lambda function.
Covers parse_email(), all helper functions, lambda_handler() routing, and DynamoDB storage.
"""
import json
import sys
import os
from unittest.mock import patch, MagicMock
import pytest
from moto import mock_aws
import boto3

# Clear any cached lambda_function module from other test files
sys.modules.pop('lambda_function', None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda/email_parser'))
import lambda_function as lf


# ---------------------------------------------------------------------------
# Shared raw-email builders
# ---------------------------------------------------------------------------

def make_raw_email(
    from_addr='Siobhan Murphy <siobhan.murphy@emaildemo.ie>',
    to_addr='support@demohealth.ie',
    subject='Claim status enquiry',
    body='I would like to check the status of my claim for POL-IE-123456.',
    date='Mon, 10 Mar 2026 09:00:00 +0000',
    message_id='<msg001@mail.emaildemo.ie>',
    references=None,
    extra_headers='',
):
    refs_line = f'References: {references}\n' if references else ''
    return (
        f'From: {from_addr}\n'
        f'To: {to_addr}\n'
        f'Subject: {subject}\n'
        f'Date: {date}\n'
        f'Message-ID: {message_id}\n'
        f'{refs_line}'
        f'{extra_headers}'
        f'\n'
        f'{body}'
    )


MULTIPART_EMAIL = """\
From: John Doe <john@emaildemo.ie>
To: claims@demohealth.ie
Subject: Hospital claim
Date: Mon, 10 Mar 2026 10:00:00 +0000
Message-ID: <multi001@mail.emaildemo.ie>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="BOUNDARY"

--BOUNDARY
Content-Type: text/plain; charset=utf-8

I was admitted to hospital last week.

--BOUNDARY
Content-Type: text/html; charset=utf-8

<p>I was admitted to <b>hospital</b> last week.</p>

--BOUNDARY
Content-Type: application/pdf
Content-Disposition: attachment; filename="invoice.pdf"

%PDF-1.4 fake

--BOUNDARY--
"""


# ---------------------------------------------------------------------------
# parse_email — schema field coverage
# ---------------------------------------------------------------------------

class TestParseEmailSchema:
    """Verify every field in the emails.jsonl schema is present and correct."""

    def test_sender_fields_split(self):
        raw = make_raw_email(from_addr='Siobhan Murphy <siobhan@emaildemo.ie>')
        result = lf.parse_email(raw)
        assert result['sender_name'] == 'Siobhan Murphy'
        assert result['sender_email'] == 'siobhan@emaildemo.ie'

    def test_sender_email_only(self):
        raw = make_raw_email(from_addr='siobhan@emaildemo.ie')
        result = lf.parse_email(raw)
        assert result['sender_email'] == 'siobhan@emaildemo.ie'
        assert result['sender_name'] == ''

    def test_mailbox_is_to_address(self):
        raw = make_raw_email(to_addr='claims@demohealth.ie')
        result = lf.parse_email(raw)
        assert result['mailbox'] == 'claims@demohealth.ie'

    def test_subject_extracted(self):
        raw = make_raw_email(subject='My important query')
        result = lf.parse_email(raw)
        assert result['subject'] == 'My important query'

    def test_body_text_extracted(self):
        raw = make_raw_email(body='Hello, I need help with my policy.')
        result = lf.parse_email(raw)
        assert 'Hello, I need help with my policy.' in result['body_text']

    def test_received_at_iso8601_utc(self):
        raw = make_raw_email(date='Mon, 10 Mar 2026 09:00:00 +0000')
        result = lf.parse_email(raw)
        assert result['received_at'] == '2026-03-10T09:00:00Z'

    def test_received_at_timezone_converted_to_utc(self):
        raw = make_raw_email(date='Mon, 10 Mar 2026 11:00:00 +0200')
        result = lf.parse_email(raw)
        assert result['received_at'] == '2026-03-10T09:00:00Z'

    def test_received_at_fallback_when_missing(self):
        raw = make_raw_email(date='')
        result = lf.parse_email(raw)
        assert result['received_at'].endswith('Z')

    def test_channel_always_email(self):
        raw = make_raw_email()
        assert lf.parse_email(raw)['channel'] == 'email'

    def test_detected_language_always_en(self):
        raw = make_raw_email()
        assert lf.parse_email(raw)['detected_language'] == 'en'

    def test_status_in_demo_new(self):
        raw = make_raw_email()
        assert lf.parse_email(raw)['status_in_demo'] == 'new'

    def test_confidence_level_pending(self):
        raw = make_raw_email()
        assert lf.parse_email(raw)['confidence_level'] == 'pending'

    def test_classification_labels_empty_strings(self):
        result = lf.parse_email(make_raw_email())
        for field in ('customer_intent', 'secondary_intent', 'urgency', 'sentiment',
                      'gold_route_team', 'gold_priority', 'business_line'):
            assert result[field] == '', f"Expected empty string for {field}"

    def test_requires_human_review_true_by_default(self):
        result = lf.parse_email(make_raw_email())
        assert result['requires_human_review'] is True

    def test_customer_id_empty(self):
        assert lf.parse_email(make_raw_email())['customer_id'] == ''

    def test_missing_sender_raises(self):
        raw = make_raw_email(from_addr='')
        with pytest.raises(ValueError, match='missing sender or body'):
            lf.parse_email(raw)

    def test_missing_body_raises(self):
        raw = make_raw_email(body='')
        with pytest.raises(ValueError, match='missing sender or body'):
            lf.parse_email(raw)


# ---------------------------------------------------------------------------
# Thread / message index
# ---------------------------------------------------------------------------

class TestThreadExtraction:

    def test_thread_id_from_message_id(self):
        raw = make_raw_email(message_id='<root001@mail.ie>')
        result = lf.parse_email(raw)
        assert result['thread_id'] == 'root001@mail.ie'

    def test_thread_id_from_references_uses_first(self):
        raw = make_raw_email(
            references='<root001@mail.ie> <mid002@mail.ie>',
            message_id='<mid003@mail.ie>',
        )
        result = lf.parse_email(raw)
        assert result['thread_id'] == 'root001@mail.ie'

    def test_message_index_1_for_first_message(self):
        raw = make_raw_email()  # no References header
        assert lf.parse_email(raw)['message_index'] == 1

    def test_message_index_increments_with_references(self):
        raw = make_raw_email(references='<r1@mail.ie> <r2@mail.ie>')
        # 2 references → 3rd message in thread
        assert lf.parse_email(raw)['message_index'] == 3


# ---------------------------------------------------------------------------
# Multipart body extraction
# ---------------------------------------------------------------------------

class TestBodyExtraction:

    def test_plain_text_extracted_from_multipart(self):
        result = lf.parse_email(MULTIPART_EMAIL)
        assert 'admitted to hospital' in result['body_text']

    def test_html_extracted_from_multipart(self):
        result = lf.parse_email(MULTIPART_EMAIL)
        assert '<p>' in result['body_html']

    def test_single_part_html_only_raises(self):
        """Single-part HTML emails (no plain text) are rejected — body_text is required."""
        raw = (
            'From: Alice <alice@emaildemo.ie>\nTo: support@demohealth.ie\n'
            'Subject: HTML query\nDate: Mon, 10 Mar 2026 09:00:00 +0000\n'
            'Content-Type: text/html\n\n'
            '<p>Hello</p>'
        )
        with pytest.raises(ValueError, match='missing sender or body'):
            lf.parse_email(raw)


# ---------------------------------------------------------------------------
# Attachment counting
# ---------------------------------------------------------------------------

class TestAttachmentCounting:

    def test_attachment_detected_in_multipart(self):
        result = lf.parse_email(MULTIPART_EMAIL)
        assert result['has_attachment'] is True
        assert result['attachment_count'] == 1

    def test_no_attachment_plain_email(self):
        result = lf.parse_email(make_raw_email())
        assert result['has_attachment'] is False
        assert result['attachment_count'] == 0


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

class TestEntityExtraction:

    def test_policy_number_extracted_from_body(self):
        raw = make_raw_email(body='My policy is POL-IE-654321, please advise.')
        assert lf.parse_email(raw)['policy_number'] == 'POL-IE-654321'

    def test_policy_number_extracted_from_subject(self):
        raw = make_raw_email(subject='Query re POL-IE-111222', body='Please help.')
        assert lf.parse_email(raw)['policy_number'] == 'POL-IE-111222'

    def test_policy_number_case_insensitive(self):
        raw = make_raw_email(body='Ref: pol-ie-999888')
        assert lf.parse_email(raw)['policy_number'] == 'POL-IE-999888'

    def test_policy_number_absent(self):
        raw = make_raw_email(body='I have a question about coverage.')
        assert lf.parse_email(raw)['policy_number'] == ''

    def test_member_id_extracted(self):
        raw = make_raw_email(body='My member ID is MEM-042001.')
        assert lf.parse_email(raw)['member_id'] == 'MEM-042001'

    def test_member_id_absent(self):
        raw = make_raw_email(body='No member ID mentioned here.')
        assert lf.parse_email(raw)['member_id'] == ''


# ---------------------------------------------------------------------------
# PII detection
# ---------------------------------------------------------------------------

class TestPIIDetection:

    def test_email_address_triggers_pii(self):
        raw = make_raw_email(body='Contact me at other@emaildemo.ie')
        assert lf.parse_email(raw)['pii_present'] is True

    def test_irish_phone_triggers_pii(self):
        # Regex anchors on word boundary; use 0xx format (starts with word char)
        raw = make_raw_email(body='Call me on 0861234567')
        assert lf.parse_email(raw)['pii_present'] is True

    def test_ppsn_triggers_pii(self):
        raw = make_raw_email(body='My PPSN is 1234567A')
        assert lf.parse_email(raw)['pii_present'] is True

    def test_no_pii(self):
        raw = make_raw_email(body='I need help with my claim please.')
        assert lf.parse_email(raw)['pii_present'] is False


# ---------------------------------------------------------------------------
# Medical term detection
# ---------------------------------------------------------------------------

class TestMedicalTermDetection:

    @pytest.mark.parametrize('term', [
        'hospital', 'MRI', 'pre-authorisation', 'consultant', 'maternity',
        'physiotherapy', 'oncology', 'prescription',
    ])
    def test_known_medical_term_detected(self, term):
        raw = make_raw_email(body=f'I need help regarding my {term} appointment.')
        assert lf.parse_email(raw)['medical_terms_present'] is True

    def test_no_medical_terms(self):
        raw = make_raw_email(body='I would like to update my payment details.')
        assert lf.parse_email(raw)['medical_terms_present'] is False


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_parse_date_valid_rfc2822(self):
        result = lf._parse_date('Mon, 10 Mar 2026 12:00:00 +0000')
        assert result == '2026-03-10T12:00:00Z'

    def test_parse_date_invalid_returns_now(self):
        result = lf._parse_date('not-a-date')
        assert result.endswith('Z')

    def test_parse_date_empty_returns_now(self):
        result = lf._parse_date('')
        assert result.endswith('Z')

    def test_extract_policy_number_present(self):
        assert lf._extract_policy_number('Ref POL-IE-000001') == 'POL-IE-000001'

    def test_extract_policy_number_absent(self):
        assert lf._extract_policy_number('No policy here') == ''

    def test_extract_member_id_present(self):
        assert lf._extract_member_id('Member MEM-123456') == 'MEM-123456'

    def test_extract_member_id_absent(self):
        assert lf._extract_member_id('No member here') == ''

    def test_detect_pii_email(self):
        assert lf._detect_pii('Send to foo@bar.ie') is True

    def test_detect_pii_phone_irish(self):
        assert lf._detect_pii('Call 0861234567') is True

    def test_detect_pii_none(self):
        assert lf._detect_pii('No personal info here') is False

    def test_detect_medical_terms_true(self):
        assert lf._detect_medical_terms('I had a scan last week') is True

    def test_detect_medical_terms_false(self):
        assert lf._detect_medical_terms('My payment failed') is False

    def test_redact_pii_masks_email(self):
        result = lf.redact_pii('customer@example.com')
        assert '***@' in result
        assert 'customer' not in result


# ---------------------------------------------------------------------------
# lambda_handler — direct invocation and S3 event routing
# ---------------------------------------------------------------------------

class TestLambdaHandler:

    RAW_EMAIL = make_raw_email()

    @mock_aws
    def _setup_aws(self):
        """Create mock S3 bucket and DynamoDB table, return clients."""
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='test-emails-bucket')
        s3.put_object(
            Bucket='test-emails-bucket',
            Key='emails/test.eml',
            Body=self.RAW_EMAIL.encode('utf-8'),
        )

        dynamo = boto3.resource('dynamodb', region_name='us-east-1')
        dynamo.create_table(
            TableName='test-emails',
            KeySchema=[{'AttributeName': 'email_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'email_id', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        return s3, dynamo

    @mock_aws
    def test_direct_invocation_success(self, lambda_context):
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='test-emails-bucket')
        s3.put_object(Bucket='test-emails-bucket', Key='emails/test.eml',
                      Body=self.RAW_EMAIL.encode('utf-8'))

        dynamo = boto3.resource('dynamodb', region_name='us-east-1')
        dynamo.create_table(
            TableName='test-emails',
            KeySchema=[{'AttributeName': 'email_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'email_id', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )

        event = {'bucket': 'test-emails-bucket', 'key': 'emails/test.eml'}
        result = lf.lambda_handler(event, lambda_context)

        assert result['statusCode'] == 200
        assert 'email_id' in result
        data = result['parsed_data']
        assert data['sender_email'] == 'siobhan.murphy@emaildemo.ie'
        assert data['subject'] == 'Claim status enquiry'
        assert data['processing_status'] == 'parsed'
        assert data['s3_bucket'] == 'test-emails-bucket'
        assert data['s3_key'] == 'emails/test.eml'

    @mock_aws
    def test_dynamodb_item_stored(self, lambda_context):
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='test-emails-bucket')
        s3.put_object(Bucket='test-emails-bucket', Key='emails/test.eml',
                      Body=self.RAW_EMAIL.encode('utf-8'))

        dynamo = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamo.create_table(
            TableName='test-emails',
            KeySchema=[{'AttributeName': 'email_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'email_id', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )

        event = {'bucket': 'test-emails-bucket', 'key': 'emails/test.eml'}
        result = lf.lambda_handler(event, lambda_context)
        email_id = result['email_id']

        item = table.get_item(Key={'email_id': email_id}).get('Item')
        assert item is not None
        assert item['sender_email'] == 'siobhan.murphy@emaildemo.ie'
        assert item['channel'] == 'email'

    @mock_aws
    def test_s3_event_trigger(self, lambda_context):
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='test-emails-bucket')
        s3.put_object(Bucket='test-emails-bucket', Key='emails/test.eml',
                      Body=self.RAW_EMAIL.encode('utf-8'))

        dynamo = boto3.resource('dynamodb', region_name='us-east-1')
        dynamo.create_table(
            TableName='test-emails',
            KeySchema=[{'AttributeName': 'email_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'email_id', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )

        event = {
            'Records': [{
                's3': {
                    'bucket': {'name': 'test-emails-bucket'},
                    'object': {'key': 'emails/test.eml'},
                }
            }]
        }
        result = lf.lambda_handler(event, lambda_context)
        assert result['statusCode'] == 200

    def test_missing_bucket_raises(self, lambda_context):
        event = {'key': 'emails/test.eml'}
        with pytest.raises(ValueError, match='Missing bucket or key'):
            lf.lambda_handler(event, lambda_context)

    def test_missing_key_raises(self, lambda_context):
        event = {'bucket': 'test-emails-bucket'}
        with pytest.raises(ValueError, match='Missing bucket or key'):
            lf.lambda_handler(event, lambda_context)

    def test_unsupported_records_source_raises(self, lambda_context):
        event = {'Records': [{'eventSource': 'aws:sqs', 'body': '{}'}]}
        with pytest.raises(ValueError, match='Unsupported Records event source'):
            lf.lambda_handler(event, lambda_context)
