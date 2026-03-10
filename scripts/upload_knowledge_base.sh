#!/bin/bash
set -e

# InsureMail AI - Knowledge Base Upload Script

echo "========================================="
echo "InsureMail AI - Knowledge Base Upload"
echo "========================================="
echo ""

# Get project root
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Check if AWS CLI is configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo "ERROR: AWS CLI is not configured or credentials are invalid"
    exit 1
fi

echo "✓ AWS CLI configured"
echo ""

# Get bucket name from Terraform
cd "$PROJECT_ROOT/terraform"

KB_BUCKET=$(terraform output -raw knowledge_base_bucket_name 2>/dev/null)

if [ -z "$KB_BUCKET" ] || [ "$KB_BUCKET" = "" ]; then
    echo "ERROR: Could not get knowledge base bucket name from Terraform"
    echo "Please run 'terraform apply' first"
    exit 1
fi

echo "Knowledge Base Bucket: $KB_BUCKET"
echo ""

# Show current knowledge_base
echo "Current knowledge base knowledge_base:"
aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive 2>/dev/null || echo "  (none yet)"
echo ""

# Upload options
echo "========================================="
echo "Upload Options"
echo "========================================="
echo ""
echo "1) Upload test/sample knowledge_base (from tests/test_data/knowledge_base/)"
echo "2) Upload custom document(s)"
echo "3) List current knowledge_base"
echo "4) Delete all knowledge_base"
echo "5) Exit"
echo ""
read -p "Select option [1-5]: " OPTION

case $OPTION in
    1)
        echo ""
        echo "Uploading test knowledge_base..."
        echo ""

        # Check if test data exists
        if [ ! -d "$PROJECT_ROOT/tests/test_data/knowledge_base" ]; then
            echo "ERROR: Test data directory not found"
            exit 1
        fi

        # Upload all files in knowledge_base directory
        aws s3 sync "$PROJECT_ROOT/tests/test_data/knowledge_base/" "s3://$KB_BUCKET/knowledge_base/" \
            --exclude "*.md" \
            --exclude ".gitkeep"

        echo ""
        echo "✓ Test knowledge_base uploaded"
        echo ""
        echo "Uploaded files:"
        aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive
        echo ""
        echo "Note: RAG ingestion Lambda will automatically process these knowledge_base"
        echo "Check CloudWatch Logs: /aws/lambda/insuremail-ai-dev-rag-ingestion"
        ;;

    2)
        echo ""
        read -p "Enter path to file or directory: " UPLOAD_PATH

        if [ ! -e "$UPLOAD_PATH" ]; then
            echo "ERROR: File or directory not found: $UPLOAD_PATH"
            exit 1
        fi

        if [ -d "$UPLOAD_PATH" ]; then
            # Upload directory
            echo "Uploading directory: $UPLOAD_PATH"
            aws s3 sync "$UPLOAD_PATH" "s3://$KB_BUCKET/knowledge_base/"
        else
            # Upload single file
            FILENAME=$(basename "$UPLOAD_PATH")
            echo "Uploading file: $FILENAME"
            aws s3 cp "$UPLOAD_PATH" "s3://$KB_BUCKET/knowledge_base/$FILENAME"
        fi

        echo ""
        echo "✓ Upload complete"
        echo ""
        echo "Uploaded files:"
        aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive
        ;;

    3)
        echo ""
        echo "Current knowledge_base in knowledge base:"
        aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive
        echo ""

        # Count knowledge_base
        DOC_COUNT=$(aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive | wc -l | xargs)
        echo "Total knowledge_base: $DOC_COUNT"
        echo ""

        # Check DynamoDB for processed embeddings
        TABLE_NAME=$(terraform output -raw embeddings_table_name 2>/dev/null)
        if [ ! -z "$TABLE_NAME" ]; then
            EMBEDDING_COUNT=$(aws dynamodb scan --table-name "$TABLE_NAME" --select "COUNT" --query "Count" --output text 2>/dev/null || echo "0")
            echo "Processed embeddings: $EMBEDDING_COUNT"
        fi
        ;;

    4)
        echo ""
        echo "⚠ WARNING: This will delete ALL knowledge_base from the knowledge base!"
        read -p "Are you sure? (type 'yes' to confirm): " CONFIRM

        if [ "$CONFIRM" = "yes" ]; then
            echo "Deleting all knowledge_base..."
            aws s3 rm "s3://$KB_BUCKET/knowledge_base/" --recursive
            echo "✓ All knowledge_base deleted"

            # Also clear DynamoDB embeddings
            read -p "Also delete processed embeddings from DynamoDB? (y/n): " DELETE_EMB
            if [ "$DELETE_EMB" = "y" ] || [ "$DELETE_EMB" = "Y" ]; then
                TABLE_NAME=$(terraform output -raw embeddings_table_name 2>/dev/null)
                if [ ! -z "$TABLE_NAME" ]; then
                    echo "Clearing embeddings table..."
                    # Note: This is a simple approach; for large tables use batch delete
                    aws dynamodb scan --table-name "$TABLE_NAME" --attributes-to-get "doc_id" \
                        --query "Items[].doc_id.S" --output text | \
                        xargs -I {} aws dynamodb delete-item --table-name "$TABLE_NAME" --key "{\"doc_id\":{\"S\":\"{}\"}}"
                    echo "✓ Embeddings cleared"
                fi
            fi
        else
            echo "Cancelled"
        fi
        ;;

    5)
        echo "Exiting"
        exit 0
        ;;

    *)
        echo "Invalid option"
        exit 1
        ;;
esac

echo ""
echo "========================================="
echo "Next Steps"
echo "========================================="
echo ""
echo "1. Wait ~30 seconds for Lambda to process knowledge_base"
echo "2. Check CloudWatch Logs:"
echo "   aws logs tail /aws/lambda/insuremail-ai-dev-rag-ingestion --follow"
echo ""
echo "3. Verify embeddings in DynamoDB:"
echo "   aws dynamodb scan --table-name $(terraform output -raw embeddings_table_name) --select COUNT"
echo ""
echo "4. Test RAG retrieval:"
echo "   Send a test email and check if relevant knowledge_base are retrieved"
echo ""
