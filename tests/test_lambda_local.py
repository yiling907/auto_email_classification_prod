"""
Local Lambda Function Tests
Run these tests before deploying to verify Lambda logic
"""
import json
import sys
import os

# Add lambda directories to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda', 'email_parser'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda', 'rag_retrieval'))

def test_email_parsing():
    """Test email parsing function"""
    print("Testing email parsing...")

    # Mock email content
    raw_email = """From: test@example.com
To: support@insuremailai.com
Subject: Test Email
Date: Mon, 4 Mar 2026 10:00:00 +0000

This is a test email body.
"""

    try:
        from lambda_function import parse_email

        result = parse_email(raw_email)

        assert 'from_address' in result
        assert 'subject' in result
        assert 'body' in result
        assert result['subject'] == 'Test Email'

        print("✓ Email parsing test passed")
        return True

    except Exception as e:
        print(f"✗ Email parsing test failed: {str(e)}")
        return False


def test_cosine_similarity():
    """Test cosine similarity calculation"""
    print("Testing cosine similarity...")

    try:
        # Import from rag_retrieval
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda', 'rag_retrieval'))
        from lambda_function import cosine_similarity

        # Test identical vectors
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [1.0, 2.0, 3.0]
        similarity = cosine_similarity(vec1, vec2)

        assert abs(similarity - 1.0) < 0.0001, f"Expected 1.0, got {similarity}"

        # Test orthogonal vectors
        vec3 = [1.0, 0.0]
        vec4 = [0.0, 1.0]
        similarity2 = cosine_similarity(vec3, vec4)

        assert abs(similarity2) < 0.0001, f"Expected 0.0, got {similarity2}"

        print("✓ Cosine similarity test passed")
        return True

    except Exception as e:
        print(f"✗ Cosine similarity test failed: {str(e)}")
        return False


def test_pii_redaction():
    """Test PII redaction"""
    print("Testing PII redaction...")

    try:
        from lambda_function import redact_pii

        # Test email redaction
        text = "john.doe@example.com"
        redacted = redact_pii(text)

        assert 'joh***@example.com' in redacted
        assert 'john.doe' not in redacted

        print("✓ PII redaction test passed")
        return True

    except Exception as e:
        print(f"✗ PII redaction test failed: {str(e)}")
        return False


def main():
    """Run all tests"""
    print("=" * 50)
    print("Running Local Lambda Tests")
    print("=" * 50)
    print()

    results = []

    # Run tests
    results.append(test_email_parsing())
    results.append(test_pii_redaction())
    results.append(test_cosine_similarity())

    print()
    print("=" * 50)
    print(f"Tests Passed: {sum(results)}/{len(results)}")
    print("=" * 50)

    return all(results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
