# Deploy InsureMail AI Dashboard to AWS

This guide explains how to deploy the React dashboard to AWS S3 with optional CloudFront CDN.

## Prerequisites

- ✅ AWS CLI configured with credentials
- ✅ Node.js >= 18 installed
- ✅ Backend API deployed (Terraform)
- ✅ API Gateway URL available

## Quick Start

### One-Command Deployment

```bash
./scripts/deploy_dashboard.sh
```

This script will:
1. ✅ Get API Gateway URL from Terraform
2. ✅ Install npm dependencies (if needed)
3. ✅ Create `.env` file with API URL
4. ✅ Build the React application
5. ✅ Ask if you want to deploy to S3
6. ✅ Deploy to S3 (new or existing bucket)
7. ✅ Enable static website hosting
8. ✅ Configure public access
9. ✅ Optionally set up CloudFront CDN
10. ✅ Provide the dashboard URL

## Deployment Options

### Option 1: Deploy to New S3 Bucket (Recommended)

The script will create a new bucket with a unique name:

```bash
./scripts/deploy_dashboard.sh

# Select: 1) Deploy to S3 (new bucket)
# Enter bucket name (or press Enter for auto-generated name)
# Enter AWS region (default: us-east-1)
```

**What happens:**
- Creates S3 bucket
- Uploads built files
- Enables static website hosting
- Configures bucket policy for public access
- Provides website URL

**Example Output:**
```
Dashboard URL:
  http://insuremail-ai-dashboard-1234567890.s3-website-us-east-1.amazonaws.com
```

### Option 2: Deploy to Existing S3 Bucket

Use an existing bucket you already have:

```bash
./scripts/deploy_dashboard.sh

# Select: 2) Deploy to S3 (existing bucket)
# Enter your bucket name
# Enter AWS region
```

**Requirements:**
- Bucket must exist
- You must have write permissions
- Bucket should be configured for static hosting (or script will do it)

### Option 3: Build Only (No Deployment)

Just build the React app without deploying:

```bash
./scripts/deploy_dashboard.sh

# Select: 3) Skip deployment (build only)
```

Build output will be in `dashboard/frontend/dist/`

## CloudFront Setup (Optional)

After deploying to S3, the script offers to set up CloudFront CDN:

```
Would you like to set up CloudFront CDN now? (y/n): y
```

**Benefits of CloudFront:**
- ✅ HTTPS enabled by default
- ✅ Global CDN for faster loading
- ✅ Better security (DDoS protection)
- ✅ Custom domain support
- ✅ SSL/TLS certificates

**Note:** CloudFront distribution takes 10-15 minutes to deploy.

## Manual Deployment Steps

If you prefer to deploy manually:

### Step 1: Build Dashboard

```bash
cd dashboard/frontend

# Install dependencies
npm install

# Get API URL
API_URL=$(cd ../../terraform && terraform output -raw api_gateway_url)

# Create .env file
echo "VITE_API_BASE_URL=$API_URL" > .env

# Build
npm run build
```

### Step 2: Create S3 Bucket

```bash
# Set variables
BUCKET_NAME="my-insuremail-dashboard"
REGION="us-east-1"

# Create bucket
aws s3 mb s3://$BUCKET_NAME --region $REGION
```

### Step 3: Upload Files

```bash
# Upload all files with public-read ACL
aws s3 sync dist/ s3://$BUCKET_NAME/ --delete --acl public-read
```

### Step 4: Enable Static Website Hosting

```bash
aws s3 website s3://$BUCKET_NAME \
  --index-document index.html \
  --error-document index.html
```

### Step 5: Set Bucket Policy

Create `bucket-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

Apply policy:

```bash
aws s3api put-bucket-policy --bucket $BUCKET_NAME --policy file://bucket-policy.json
```

### Step 6: Configure Public Access

```bash
aws s3api put-public-access-block \
  --bucket $BUCKET_NAME \
  --public-access-block-configuration \
  "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"
```

### Step 7: Access Dashboard

```bash
# Get website URL
echo "http://$BUCKET_NAME.s3-website-$REGION.amazonaws.com"
```

## CloudFront Manual Setup

### Create Distribution

```bash
aws cloudfront create-distribution \
  --origin-domain-name $BUCKET_NAME.s3-website-$REGION.amazonaws.com \
  --default-root-object index.html
```

### Get CloudFront Domain

```bash
aws cloudfront list-distributions \
  --query "DistributionList.Items[0].DomainName" \
  --output text
```

### Access via HTTPS

```
https://d123456abcdef.cloudfront.net
```

## Updating the Dashboard

### After Code Changes

```bash
# Navigate to dashboard
cd dashboard/frontend

# Build
npm run build

# Upload to S3
aws s3 sync dist/ s3://YOUR-BUCKET-NAME/ --delete --acl public-read
```

### With CloudFront

After uploading to S3, invalidate CloudFront cache:

```bash
# Get distribution ID
DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[0].Id" --output text)

# Create invalidation
aws cloudfront create-invalidation \
  --distribution-id $DIST_ID \
  --paths "/*"
```

## Custom Domain Setup

### Step 1: Request SSL Certificate (ACM)

```bash
# Must be in us-east-1 for CloudFront
aws acm request-certificate \
  --domain-name dashboard.yourdomain.com \
  --validation-method DNS \
  --region us-east-1
```

### Step 2: Validate Certificate

Follow the DNS validation instructions in AWS Console.

### Step 3: Update CloudFront Distribution

Add custom domain and SSL certificate in CloudFront settings.

### Step 4: Create Route 53 Record

Point your domain to the CloudFront distribution:

```bash
# Create A record alias to CloudFront
aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR-ZONE-ID \
  --change-batch file://dns-record.json
```

## Troubleshooting

### Issue: 403 Forbidden Error

**Symptoms:** Cannot access website, getting 403 error

**Solutions:**
1. Check bucket policy is applied
2. Verify public access block settings
3. Ensure files have public-read ACL
4. Check bucket name in URL is correct

```bash
# Fix public access
aws s3api put-public-access-block \
  --bucket $BUCKET_NAME \
  --public-access-block-configuration \
  "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"

# Re-upload with public-read
aws s3 sync dist/ s3://$BUCKET_NAME/ --delete --acl public-read
```

### Issue: API Not Working (CORS Errors)

**Symptoms:** Dashboard loads but shows errors, no data

**Solutions:**
1. Verify API Gateway is deployed
2. Check `.env` file has correct API URL
3. Ensure API Gateway has CORS enabled
4. Check browser console for specific errors

```bash
# Verify API URL
cd terraform
terraform output api_gateway_url

# Test API endpoint
curl $(terraform output -raw api_gateway_url)/api/dashboard/overview
```

### Issue: Old Content Showing After Update

**Symptoms:** Dashboard not showing latest changes

**Solutions:**

For S3 only:
```bash
# Clear browser cache
# Or force refresh: Ctrl+Shift+R (Windows/Linux), Cmd+Shift+R (Mac)
```

For CloudFront:
```bash
# Invalidate CloudFront cache
DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[0].Id" --output text)
aws cloudfront create-invalidation --distribution-id $DIST_ID --paths "/*"
```

### Issue: npm install Fails

**Symptoms:** Dependencies installation errors

**Solutions:**
```bash
cd dashboard/frontend

# Clear npm cache
npm cache clean --force

# Delete node_modules and package-lock.json
rm -rf node_modules package-lock.json

# Reinstall
npm install
```

### Issue: Build Fails

**Symptoms:** `npm run build` returns errors

**Solutions:**
1. Check Node.js version (need >= 18)
2. Verify all dependencies installed
3. Check for syntax errors in code
4. Review build output for specific errors

```bash
# Check Node version
node --version

# Should be v18.x.x or higher
```

## Cost Estimation

### S3 Static Hosting

- **Storage:** ~$0.023/GB/month
- **Requests:** ~$0.0004 per 1,000 GET requests
- **Data Transfer:** ~$0.09/GB (first GB free)

**Estimated:** <$1/month for moderate traffic

### CloudFront CDN

- **Data Transfer:** ~$0.085/GB for first 10TB
- **Requests:** ~$0.0075 per 10,000 requests
- **SSL Certificate:** Free (with ACM)

**Estimated:** $5-20/month depending on traffic

### Total Monthly Cost

- **Low traffic** (< 10K visitors): $1-5
- **Medium traffic** (10K-100K visitors): $5-20
- **High traffic** (100K+ visitors): $20-100

## Security Best Practices

### S3 Bucket Security

✅ **Do:**
- Use bucket policies instead of ACLs
- Enable versioning for rollback capability
- Enable access logging
- Use least-privilege policies

❌ **Don't:**
- Make entire bucket public (only objects)
- Store sensitive data in public bucket
- Forget to set up HTTPS (use CloudFront)

### CloudFront Security

✅ **Recommended:**
- Enable AWS WAF for protection
- Use custom SSL certificates
- Enable field-level encryption
- Set up geo-restrictions if needed
- Enable CloudFront access logs

### Environment Variables

✅ **Safe:**
- API Gateway URLs (public endpoint)
- CloudFront distribution IDs
- Region names

❌ **Never Include:**
- AWS credentials
- API keys
- Database passwords
- Internal service URLs

## Performance Optimization

### Build Optimization

```bash
# Analyze bundle size
npm run build -- --mode production

# The build process already includes:
# - Code splitting
# - Tree shaking
# - Minification
# - Gzip compression
```

### S3 Optimization

```bash
# Upload with content encoding
aws s3 sync dist/ s3://$BUCKET_NAME/ \
  --delete \
  --acl public-read \
  --content-encoding gzip \
  --metadata-directive REPLACE
```

### CloudFront Optimization

- Enable compression
- Set appropriate cache TTLs
- Use Lambda@Edge for dynamic content
- Enable HTTP/2 and HTTP/3

## Monitoring

### CloudWatch Metrics

```bash
# View S3 bucket metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name NumberOfObjects \
  --dimensions Name=BucketName,Value=$BUCKET_NAME \
  --statistics Average \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-31T23:59:59Z \
  --period 86400
```

### CloudFront Metrics

```bash
# View CloudFront metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/CloudFront \
  --metric-name Requests \
  --dimensions Name=DistributionId,Value=$DIST_ID \
  --statistics Sum \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-31T23:59:59Z \
  --period 3600
```

## Cleanup

### Delete S3 Deployment

```bash
# Empty bucket
aws s3 rm s3://$BUCKET_NAME --recursive

# Delete bucket
aws s3 rb s3://$BUCKET_NAME
```

### Delete CloudFront Distribution

```bash
# Disable distribution first
aws cloudfront update-distribution \
  --id $DIST_ID \
  --distribution-config file://disabled-config.json

# Wait for deployment
aws cloudfront wait distribution-deployed --id $DIST_ID

# Delete distribution
aws cloudfront delete-distribution --id $DIST_ID --if-match $ETAG
```

## Summary

**Recommended Deployment Flow:**

1. ✅ Run automated script: `./scripts/deploy_dashboard.sh`
2. ✅ Choose "Deploy to S3 (new bucket)"
3. ✅ Let it auto-generate bucket name
4. ✅ Say "yes" to CloudFront setup (for HTTPS)
5. ✅ Wait 10-15 minutes for CloudFront
6. ✅ Access via HTTPS CloudFront URL

**For Production:**
- Add custom domain
- Set up SSL certificate
- Enable CloudFront WAF
- Configure monitoring
- Set up backups
- Review cost optimization

The dashboard is now live and accessible globally! 🚀
