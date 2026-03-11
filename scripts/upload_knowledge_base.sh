#!/usr/bin/env bash
set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}   InsureMail AI — Knowledge Base Upload${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo ""

# Get project root
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Check if AWS CLI is configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}ERROR: AWS CLI is not configured or credentials are invalid${NC}"
    exit 1
fi

echo -e "${GREEN}✓ AWS CLI configured${NC}"
echo ""

# Get bucket name from Terraform
cd "$PROJECT_ROOT/terraform"

KB_BUCKET=$(terraform output -raw knowledge_base_bucket_name 2>/dev/null)

if [ -z "$KB_BUCKET" ] || [ "$KB_BUCKET" = "" ]; then
    echo -e "${RED}ERROR: Could not get knowledge base bucket name from Terraform${NC}"
    echo "Please run 'terraform apply' first"
    exit 1
fi

echo "Knowledge Base Bucket: $KB_BUCKET"
echo ""

# Show current documents
echo "Current documents:"
aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive 2>/dev/null || echo "  (none yet)"
echo ""

# Upload options
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}   Upload Options${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo ""
echo "1) Upload documents (from tests/test_data/knowledge_base/)"
echo "2) Upload custom document(s)"
echo "3) List current documents"
echo "4) Delete all documents"
echo "5) Exit"
echo ""
read -p "Select option [1-5]: " OPTION

case $OPTION in
    1)
        echo ""
        echo "Uploading documents..."
        echo ""

        # Check if test data exists
        if [ ! -d "$PROJECT_ROOT/tests/test_data/knowledge_base" ]; then
            echo -e "${RED}ERROR: Test data directory not found${NC}"
            exit 1
        fi

        # Upload all files in knowledge_base directory
        aws s3 sync "$PROJECT_ROOT/tests/test_data/knowledge_base/" "s3://$KB_BUCKET/knowledge_base/" \
            --exclude "*.md" \
            --exclude ".gitkeep"

        echo ""
        echo -e "${GREEN}✓ Documents uploaded${NC}"
        echo ""
        echo "Uploaded files:"
        aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive

        echo ""
        aws lambda invoke --function-name insuremail-ai-dev-rag-ingestion --payload '{}' /tmp/rag_invoke_out.json >/dev/null
        echo "RAG ingestion triggered"
        echo "Check CloudWatch Logs: /aws/lambda/insuremail-ai-dev-rag-ingestion"
        ;;

    2)
        echo ""
        read -p "Enter path to file or directory: " UPLOAD_PATH

        if [ ! -e "$UPLOAD_PATH" ]; then
            echo -e "${RED}ERROR: File or directory not found: $UPLOAD_PATH${NC}"
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
        echo -e "${GREEN}✓ Upload complete${NC}"
        echo ""
        echo "Uploaded files:"
        aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive

        echo ""
        aws lambda invoke --function-name insuremail-ai-dev-rag-ingestion --payload '{}' /tmp/rag_invoke_out.json >/dev/null
        echo "RAG ingestion triggered"
        ;;

    3)
        echo ""
        echo "Current documents in knowledge base:"
        aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive
        echo ""

        # Count documents
        DOC_COUNT=$(aws s3 ls "s3://$KB_BUCKET/knowledge_base/" --recursive | wc -l | xargs)
        echo "Total documents: $DOC_COUNT"
        echo ""

        # Check DynamoDB for processed embeddings
        TABLE_NAME=$(terraform output -raw embeddings_table_name 2>/dev/null)
        if [ -n "$TABLE_NAME" ]; then
            EMBEDDING_COUNT=$(aws dynamodb scan --table-name "$TABLE_NAME" --select COUNT --query "Count" --output text 2>/dev/null || echo "0")
            echo "Processed embeddings: $EMBEDDING_COUNT"
        fi
        ;;

    4)
        echo ""
        echo -e "${YELLOW}⚠ WARNING: This will delete ALL documents from the knowledge base!${NC}"
        read -p "Are you sure? (type 'yes' to confirm): " CONFIRM

        if [ "$CONFIRM" = "yes" ]; then
            echo "Deleting all documents..."
            aws s3 rm "s3://$KB_BUCKET/knowledge_base/" --recursive
            echo -e "${GREEN}✓ All documents deleted${NC}"

            # Also clear DynamoDB embeddings
            read -p "Also delete processed embeddings from DynamoDB? (y/n): " DELETE_EMB
            if [ "$DELETE_EMB" = "y" ] || [ "$DELETE_EMB" = "Y" ]; then
                TABLE_NAME=$(terraform output -raw embeddings_table_name 2>/dev/null)
                if [ -n "$TABLE_NAME" ]; then
                    echo "Clearing embeddings table..."
                    python3 -c "
import boto3, json
table = boto3.resource('dynamodb').Table('$TABLE_NAME')
items = table.scan(ProjectionExpression='doc_id')['Items']
with table.batch_writer() as batch:
    for item in items:
        batch.delete_item(Key={'doc_id': item['doc_id']})
print(f'Deleted {len(items)} embeddings')
"
                    echo -e "${GREEN}✓ Embeddings cleared${NC}"
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
        echo -e "${RED}Invalid option${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}   Next Steps${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo ""
echo "1. Wait ~30 seconds for Lambda to process documents"
echo "2. Check CloudWatch Logs:"
echo "   aws logs tail /aws/lambda/insuremail-ai-dev-rag-ingestion --follow"
echo ""
echo "3. Verify embeddings in DynamoDB:"
echo "   aws dynamodb scan --table-name $(terraform output -raw embeddings_table_name) --select COUNT"
echo ""
echo "4. Test RAG retrieval:"
echo "   Send a test email and check if relevant documents are retrieved"
echo ""
