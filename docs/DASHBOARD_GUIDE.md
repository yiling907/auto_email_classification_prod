# InsureMail AI Dashboard Guide

## Overview

The InsureMail AI Dashboard provides a comprehensive web interface for monitoring and managing the email processing system. It consists of a backend API (AWS Lambda + API Gateway) and a modern React frontend.

## Architecture

```
┌─────────────────┐
│  React Frontend │  (Vite + React 18)
│   (Port 3000)   │
└────────┬────────┘
         │ HTTP
         ↓
┌─────────────────┐
│  API Gateway    │  (REST API)
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  API Handler    │  (Lambda Function)
│    Lambda       │
└────────┬────────┘
         │
    ┌────┴────┐
    ↓         ↓
┌─────────┐ ┌─────────┐
│DynamoDB │ │   S3    │
└─────────┘ └─────────┘
```

## Components Built

### Backend API

#### Lambda Function: `api_handlers`
- **Location**: `lambda/api_handlers/lambda_function.py`
- **Endpoints**:
  - `GET /api/dashboard/overview` - Dashboard statistics
  - `GET /api/emails` - List all emails
  - `GET /api/emails?confidence_level={level}` - Filtered emails
  - `GET /api/email/{emailId}` - Email details
  - `GET /api/metrics/models` - Model performance metrics
  - `GET /api/metrics/rag` - RAG effectiveness metrics

#### API Gateway
- **Type**: REST API (Regional)
- **CORS**: Enabled for all endpoints
- **Stage**: `dev` (environment-based)
- **Integration**: Lambda Proxy integration

### Frontend Dashboard

#### Technologies
- **React**: 18.2.0
- **Vite**: Build tool and dev server
- **React Router**: Client-side routing
- **Axios**: HTTP client
- **Recharts**: Data visualization

#### Pages

1. **Dashboard (/)** - Overview Page
   - Total emails processed
   - Average confidence score
   - Auto-response rate
   - Confidence distribution pie chart
   - Recent emails table

2. **Emails (/emails)** - Email List
   - Paginated email list
   - Filter by confidence level
   - Search and sorting
   - Quick access to details

3. **Email Detail (/email/:id)** - Detailed View
   - Full email content
   - AI analysis results
   - Generated response
   - Processing metadata
   - Storage location

4. **Model Metrics (/models)** - Performance Comparison
   - Multi-model statistics
   - Latency comparison chart
   - Success rate visualization
   - Cost analysis
   - Detailed metrics table

5. **RAG Metrics (/rag)** - Knowledge Base Stats
   - Total documents count
   - Document type distribution
   - System status
   - RAG effectiveness metrics

## Deployment Instructions

### Step 1: Deploy Backend (Terraform)

The backend is automatically deployed with Terraform:

```bash
cd terraform
terraform apply
```

This creates:
- API Handler Lambda function
- API Gateway REST API
- All necessary IAM permissions

Get the API URL:
```bash
terraform output api_gateway_url
```

### Step 2: Build and Deploy Frontend

#### Option A: Automated Script

```bash
./scripts/deploy_dashboard.sh
```

This script will:
1. Install npm dependencies
2. Create `.env` file with API URL
3. Build the React application
4. Provide deployment instructions

#### Option B: Manual Steps

1. Install dependencies:
```bash
cd dashboard/frontend
npm install
```

2. Create `.env` file:
```bash
echo "VITE_API_BASE_URL=<your-api-gateway-url>" > .env
```

3. Build:
```bash
npm run build
```

4. Deploy to S3:
```bash
aws s3 mb s3://insuremail-ai-dashboard
aws s3 sync dist/ s3://insuremail-ai-dashboard/ --delete
aws s3 website s3://insuremail-ai-dashboard/ \
  --index-document index.html \
  --error-document index.html
```

### Step 3: Test Locally

Run development server:
```bash
cd dashboard/frontend
npm run dev
```

Visit http://localhost:3000

## Features

### Real-Time Monitoring
✅ Email processing statistics
✅ Confidence score tracking
✅ Auto-response rate monitoring
✅ System health status

### Data Visualization
✅ Pie charts for distributions
✅ Bar charts for comparisons
✅ Interactive tooltips
✅ Responsive design

### Email Management
✅ Browse all processed emails
✅ Filter by confidence level
✅ View detailed trace
✅ See AI-generated responses

### Performance Analytics
✅ Compare multiple LLM models
✅ Track latency and costs
✅ Monitor success rates
✅ Historical trends

### Knowledge Base Insights
✅ Document statistics
✅ Type distribution
✅ Coverage analysis
✅ System status

## API Response Examples

### Dashboard Overview
```json
{
  "total_emails": 25,
  "avg_confidence": 0.78,
  "auto_response_rate": 68.0,
  "confidence_distribution": {
    "high": 17,
    "medium": 5,
    "low": 2,
    "pending": 1
  },
  "recent_emails": [...]
}
```

### Email Detail
```json
{
  "email_id": "b7bff410-09b6-42cf-978a-971c2edfeca4",
  "from_address": "joh***@example.com",
  "subject": "Question about my claim status",
  "body": "...",
  "confidence_score": 0.85,
  "confidence_level": "high",
  "action": "auto_response",
  "response_text": "...",
  "timestamp": "2026-03-04T16:13:28.794299Z"
}
```

### Model Metrics
```json
{
  "by_model": {
    "claude-3-haiku": {
      "total_requests": 25,
      "successful_requests": 25,
      "success_rate": 100.0,
      "avg_latency_ms": 4246.88,
      "total_cost_usd": 0.0058,
      "avg_cost_usd": 0.000231
    }
  },
  "total_metrics": 25
}
```

## Customization

### Adding New Charts

1. Install Recharts (already included):
```bash
npm install recharts
```

2. Import components:
```jsx
import { LineChart, Line, XAxis, YAxis } from 'recharts'
```

3. Use in component:
```jsx
<ResponsiveContainer width="100%" height={300}>
  <LineChart data={data}>
    <XAxis dataKey="name" />
    <YAxis />
    <Line type="monotone" dataKey="value" stroke="#667eea" />
  </LineChart>
</ResponsiveContainer>
```

### Adding New API Endpoints

1. Update `lambda/api_handlers/lambda_function.py`:
```python
if path == '/api/new-endpoint':
    response = get_new_data(event)
```

2. Add handler function:
```python
def get_new_data(event):
    # Query DynamoDB
    # Process data
    return {
        'statusCode': 200,
        'body': json.dumps(data)
    }
```

3. Redeploy with Terraform:
```bash
terraform apply
```

### Styling

- Global styles: `src/index.css`
- Component styles: `src/App.css`
- Inline styles: JSX style prop

Color scheme:
- Primary: `#667eea` (purple)
- Secondary: `#764ba2` (darker purple)
- Success: `#28a745` (green)
- Warning: `#ffc107` (yellow)
- Danger: `#dc3545` (red)
- Info: `#17a2b8` (cyan)

## Troubleshooting

### Issue: CORS Errors

**Symptoms**: Browser console shows CORS policy errors

**Solution**:
1. Verify API Gateway CORS configuration
2. Check Lambda function returns CORS headers
3. Ensure `.env` has correct API URL
4. Redeploy API Gateway stage

### Issue: API Returns 403

**Symptoms**: All API calls return 403 Forbidden

**Solution**:
1. Check Lambda IAM permissions
2. Verify API Gateway integration
3. Test Lambda function directly
4. Check CloudWatch Logs

### Issue: Charts Not Rendering

**Symptoms**: Blank space where charts should be

**Solution**:
1. Verify data format matches Recharts requirements
2. Check console for JavaScript errors
3. Ensure ResponsiveContainer has height
4. Verify recharts is installed

### Issue: Empty Data

**Symptoms**: Dashboard shows no data

**Solution**:
1. Upload test data: `./scripts/upload_test_data.sh`
2. Process emails through workflow
3. Check DynamoDB tables have data
4. Verify API endpoints return data

## Performance Optimization

### Backend
- ✅ DynamoDB PAY_PER_REQUEST (no idle costs)
- ✅ Lambda right-sized memory allocation
- ✅ Efficient DynamoDB queries
- ⏳ Consider DynamoDB caching (DAX) for high traffic

### Frontend
- ✅ Code splitting with Vite
- ✅ Lazy loading of routes
- ✅ Optimized bundle size
- ⏳ Add React.memo for expensive components
- ⏳ Implement virtual scrolling for large lists

## Security Considerations

### Current Implementation
- ✅ CORS enabled (restrict in production)
- ✅ No sensitive data in frontend
- ✅ Environment-based configuration
- ✅ IAM-based backend access

### Production Recommendations
- Add Amazon Cognito authentication
- Restrict CORS to specific domains
- Implement rate limiting
- Add CloudFront WAF rules
- Enable API Gateway API keys
- Use HTTPS only (CloudFront)

## Cost Estimation

### Backend (API)
- API Gateway: ~$3.50 per million requests
- Lambda: ~$0.20 per million requests (128MB)
- DynamoDB: Included in scan costs
- **Estimated**: <$1/month for <10K requests

### Frontend (S3 + CloudFront)
- S3 storage: ~$0.023/GB/month
- S3 requests: ~$0.005 per 1K requests
- CloudFront: ~$0.085/GB transfer
- **Estimated**: <$5/month for moderate traffic

## Next Steps

### Phase 1: Current (✅ Complete)
- ✅ Backend API implementation
- ✅ Frontend React application
- ✅ Basic visualization
- ✅ Email management
- ✅ Model metrics

### Phase 2: Enhancements (Recommended)
- [ ] Add Cognito authentication
- [ ] Implement CloudFront CDN
- [ ] Add real-time updates (WebSocket)
- [ ] Export data to CSV/PDF
- [ ] Advanced filtering and search
- [ ] Custom date range selection

### Phase 3: Advanced Features (Optional)
- [ ] A/B testing dashboard
- [ ] Cost forecasting
- [ ] Alert notifications
- [ ] Admin user management
- [ ] API documentation (Swagger)
- [ ] Mobile-responsive improvements

## Support

For issues or questions:
1. Check CloudWatch Logs for backend errors
2. Check browser console for frontend errors
3. Review API Gateway execution logs
4. Verify Terraform state: `terraform show`

## Conclusion

The InsureMail AI Dashboard provides a complete monitoring solution for the email processing system. It offers real-time insights, performance metrics, and detailed tracing capabilities, all wrapped in a modern, responsive interface.

**Status**: ✅ Production-ready for internal use
**Recommendation**: Add authentication before public deployment
