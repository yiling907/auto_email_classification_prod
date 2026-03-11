#!/usr/bin/env bash
set -e

KNOWN_BUCKET="insuremail-ai-dashboard"
KNOWN_CF_DIST="E2ADYLCS9LNMWF"

# InsureMail AI - Dashboard Deployment Script

# Function to deploy to a new S3 bucket
deploy_to_new_bucket() {
    echo ""
    echo "========================================="
    echo "Deploy to New S3 Bucket"
    echo "========================================="
    echo ""

    # Generate unique bucket name
    DEFAULT_BUCKET="insuremail-ai-dashboard-$(date +%s)"
    read -p "Enter S3 bucket name [$DEFAULT_BUCKET]: " BUCKET_NAME
    BUCKET_NAME=${BUCKET_NAME:-$DEFAULT_BUCKET}

    read -p "Enter AWS region [us-east-1]: " AWS_REGION
    AWS_REGION=${AWS_REGION:-us-east-1}

    echo ""
    echo "Creating S3 bucket: $BUCKET_NAME"

    # Create bucket
    if [ "$AWS_REGION" = "us-east-1" ]; then
        aws s3 mb s3://$BUCKET_NAME
    else
        aws s3 mb s3://$BUCKET_NAME --region $AWS_REGION
    fi

    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create S3 bucket"
        exit 1
    fi

    echo "✓ Bucket created"

    # Deploy to the bucket
    deploy_to_s3 $BUCKET_NAME $AWS_REGION
}

# Function to deploy to existing S3 bucket
deploy_to_existing_bucket() {
    echo ""
    echo "========================================="
    echo "Deploy to Existing S3 Bucket"
    echo "========================================="
    echo ""

    read -p "Enter S3 bucket name: " BUCKET_NAME
    BUCKET_NAME=${BUCKET_NAME:-$KNOWN_BUCKET}

    if [ -z "$BUCKET_NAME" ]; then
        echo "ERROR: Bucket name is required"
        exit 1
    fi

    read -p "Enter AWS region [us-east-1]: " AWS_REGION
    AWS_REGION=${AWS_REGION:-us-east-1}

    # Check if bucket exists
    if ! aws s3 ls s3://$BUCKET_NAME &> /dev/null; then
        echo "ERROR: Bucket $BUCKET_NAME does not exist or you don't have access"
        exit 1
    fi

    echo "✓ Bucket found"

    # Deploy to the bucket
    deploy_to_s3 $BUCKET_NAME $AWS_REGION
}

# Function to deploy files to S3
deploy_to_s3() {
    local BUCKET_NAME=$1
    local AWS_REGION=$2

    # Remove public access block first
    echo ""
    echo "Configuring public access settings..."
    aws s3api put-public-access-block \
        --bucket $BUCKET_NAME \
        --public-access-block-configuration \
        "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false" \
        2>/dev/null || echo "Note: Public access block settings configured"

    # Set bucket policy for public access
    echo ""
    echo "Configuring bucket policy..."

    cat > /tmp/bucket-policy-$$.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::$BUCKET_NAME/*"
    }
  ]
}
EOF

    aws s3api put-bucket-policy --bucket $BUCKET_NAME --policy file:///tmp/bucket-policy-$$.json 2>/dev/null

    if [ $? -ne 0 ]; then
        echo "WARNING: Failed to set bucket policy. You may need to configure public access manually."
    else
        echo "✓ Bucket policy configured"
    fi

    # Clean up temp file
    rm -f /tmp/bucket-policy-$$.json

    # Enable static website hosting
    echo ""
    echo "Enabling static website hosting..."
    aws s3 website s3://$BUCKET_NAME \
        --index-document index.html \
        --error-document index.html

    if [ $? -ne 0 ]; then
        echo "WARNING: Failed to enable website hosting (you may need to do this manually)"
    else
        echo "✓ Website hosting enabled"
    fi

    # Upload files (without ACL flag)
    echo ""
    echo "Uploading files to S3..."
    aws s3 sync "$DASHBOARD_DIR/dist/" "s3://$BUCKET_NAME/" --delete

    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to upload files"
        exit 1
    fi

    echo "✓ Files uploaded"

    echo ""
    echo "Invalidating CloudFront cache (/index.html)..."
    aws cloudfront create-invalidation \
        --distribution-id "$KNOWN_CF_DIST" \
        --paths "/index.html" \
        --query 'Invalidation.Id' --output text 2>/dev/null || true

    # Get website URL
    WEBSITE_URL="http://$BUCKET_NAME.s3-website-$AWS_REGION.amazonaws.com"

    echo ""
    echo "========================================="
    echo "✓ Dashboard Deployed Successfully!"
    echo "========================================="
    echo ""
    echo "Dashboard URL:"
    echo "  $WEBSITE_URL"
    echo ""
    echo "Bucket: $BUCKET_NAME"
    echo "Region: $AWS_REGION"
    echo ""
    echo "Next Steps:"
    echo "  1. Open the URL above in your browser"
    echo "  2. (Optional) Set up CloudFront CDN for HTTPS and better performance"
    echo "  3. (Optional) Configure custom domain"
    echo ""
    echo "To update the dashboard:"
    echo "  npm run build && aws s3 sync dist/ s3://$BUCKET_NAME/ --delete"
    echo ""

    # Ask if user wants to set up CloudFront
    read -p "Would you like to set up CloudFront CDN now? (y/n): " SETUP_CF

    if [ "$SETUP_CF" = "y" ] || [ "$SETUP_CF" = "Y" ]; then
        setup_cloudfront $BUCKET_NAME $AWS_REGION
    fi
}

# Function to set up CloudFront distribution
setup_cloudfront() {
    local BUCKET_NAME=$1
    local AWS_REGION=$2

    echo ""
    echo "========================================="
    echo "Setting up CloudFront Distribution"
    echo "========================================="
    echo ""
    echo "This will create a CloudFront distribution for:"
    echo "  - HTTPS access"
    echo "  - Global CDN caching"
    echo "  - Better performance"
    echo ""

    # Create CloudFront distribution
    echo "Creating CloudFront distribution (this may take 10-15 minutes)..."

    CF_CONFIG=$(cat <<EOF
{
  "CallerReference": "insuremail-dashboard-$(date +%s)",
  "Comment": "InsureMail AI Dashboard",
  "DefaultRootObject": "index.html",
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "S3-$BUCKET_NAME",
        "DomainName": "$BUCKET_NAME.s3-website-$AWS_REGION.amazonaws.com",
        "CustomOriginConfig": {
          "HTTPPort": 80,
          "HTTPSPort": 443,
          "OriginProtocolPolicy": "http-only"
        }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "S3-$BUCKET_NAME",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["GET", "HEAD"]
    },
    "ForwardedValues": {
      "QueryString": false,
      "Cookies": {
        "Forward": "none"
      }
    },
    "MinTTL": 0,
    "DefaultTTL": 86400,
    "MaxTTL": 31536000,
    "Compress": true,
    "TrustedSigners": {
      "Enabled": false,
      "Quantity": 0
    }
  },
  "CustomErrorResponses": {
    "Quantity": 1,
    "Items": [
      {
        "ErrorCode": 404,
        "ResponsePagePath": "/index.html",
        "ResponseCode": "200",
        "ErrorCachingMinTTL": 300
      }
    ]
  },
  "Enabled": true,
  "PriceClass": "PriceClass_100"
}
EOF
)

    # Save config to temp file
    echo "$CF_CONFIG" > /tmp/cf-config-$$.json

    # Create distribution
    CF_OUTPUT=$(aws cloudfront create-distribution --distribution-config file:///tmp/cf-config-$$.json 2>&1)

    if [ $? -eq 0 ]; then
        CF_DOMAIN=$(echo "$CF_OUTPUT" | grep -o '"DomainName": "[^"]*"' | head -1 | cut -d'"' -f4)

        echo "✓ CloudFront distribution created!"
        echo ""
        echo "CloudFront URL:"
        echo "  https://$CF_DOMAIN"
        echo ""
        echo "Note: It may take 10-15 minutes for the distribution to be fully deployed."
        echo "      Check status: aws cloudfront list-distributions"
    else
        echo "WARNING: Failed to create CloudFront distribution"
        echo "$CF_OUTPUT"
    fi

    # Clean up
    rm -f /tmp/cf-config-$$.json
}

echo "========================================="
echo "InsureMail AI - Dashboard Deployment"
echo "========================================="

# Get project root
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DASHBOARD_DIR="$PROJECT_ROOT/dashboard/frontend"

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js is not installed"
    exit 1
fi

# Get API Gateway URL from Terraform
cd "$PROJECT_ROOT/terraform"
API_URL=$(terraform output -raw api_gateway_url 2>/dev/null)

if [ -z "$API_URL" ]; then
    echo "ERROR: Could not get API Gateway URL from Terraform"
    echo "Please run terraform apply first"
    exit 1
fi

echo "API Gateway URL: $API_URL"
echo ""

# Navigate to dashboard directory
cd "$DASHBOARD_DIR"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Create .env file with API URL
echo "Creating .env file..."
cat > .env <<EOF
VITE_API_BASE_URL=$API_URL
EOF

# Build dashboard
echo ""
echo "Building dashboard..."
npm run build

if [ $? -ne 0 ]; then
    echo "ERROR: Dashboard build failed"
    exit 1
fi

echo "✓ Dashboard built successfully"
echo ""

# Ask user if they want to deploy to AWS
echo "========================================="
echo "Deployment Options"
echo "========================================="
echo ""
echo "Would you like to deploy the dashboard to AWS S3?"
echo ""
echo "Options:"
echo "  1) Deploy to S3 (new bucket)"
echo "  2) Deploy to S3 (existing bucket)"
echo "  3) Skip deployment (build only)"
echo ""
read -p "Select option [1-3]: " DEPLOY_OPTION

case $DEPLOY_OPTION in
    1)
        deploy_to_new_bucket
        ;;
    2)
        deploy_to_existing_bucket
        ;;
    3)
        echo ""
        echo "========================================="
        echo "Build Complete!"
        echo "========================================="
        echo ""
        echo "Build output: $DASHBOARD_DIR/dist"
        echo ""
        echo "To test locally:"
        echo "  cd $DASHBOARD_DIR"
        echo "  npm run dev"
        echo ""
        ;;
    *)
        echo "Invalid option. Exiting."
        exit 1
        ;;
esac
