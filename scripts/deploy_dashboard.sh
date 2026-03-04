#!/bin/bash
set -e

# InsureMail AI - Dashboard Deployment Script

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

# For local testing, provide instructions
echo "========================================="
echo "Dashboard Built!"
echo "========================================="
echo ""
echo "To test locally:"
echo "  cd $DASHBOARD_DIR"
echo "  npm run dev"
echo ""
echo "To deploy to S3:"
echo "  1. Create an S3 bucket for static hosting"
echo "  2. Run: aws s3 sync dist/ s3://your-bucket-name/ --delete"
echo "  3. Enable static website hosting on the bucket"
echo "  4. Optionally add CloudFront CDN"
echo ""
echo "Build output is in: $DASHBOARD_DIR/dist"
echo ""
