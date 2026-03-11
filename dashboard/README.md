# InsureMail AI Dashboard

Modern React-based dashboard for monitoring and managing the InsureMail AI email processing system.

## Technology Stack

- **Frontend Framework**: React 18
- **Build Tool**: Vite
- **Routing**: React Router DOM
- **Charts**: Recharts
- **HTTP Client**: Axios
- **Styling**: Custom CSS

## Features

### 1. Dashboard Overview
- Aggregate stats (total emails, average confidence, auto-response rate)
- Confidence distribution chart
- Model Settings board — toggle between inference models at runtime
- Recent emails list

### 2. Email Processing History
- Browse all processed emails
- Filter by confidence level, action, and processing status
- View sender, intent, urgency, sentiment, and route team per email

### 3. Email Detail
- All 37 DynamoDB fields displayed in 7 sections
- Editable LLM response textarea
- Save Draft and Send buttons to update and dispatch responses

### 4. Model Performance
- 4 tabs: Overview (latency/cost charts), Classification Accuracy (per-field scores + radar), Response Quality (eval dimensions + radar), All Records table
- Compare multiple LLM models side by side

### 5. RAG Knowledge Base
- 4 stat cards: total chunks, source files, avg chunks/file, status
- Searchable file list table showing all ingested documents

### 6. Evaluations
- Bedrock evaluation job results
- Claude-as-judge scores across quality dimensions

## API Endpoints

The dashboard consumes the following API endpoints:

- `GET /api/dashboard/overview` — Dashboard statistics
- `GET /api/emails` — List of emails (params: `confidence_level`, `action`, `processing_status`)
- `GET /api/email/{id}` — Full email record (37 fields)
- `POST /api/email/{id}` — Update `llm_response` field
- `POST /api/email/{id}/send` — Trigger email sender Lambda
- `GET /api/metrics/models` — Model performance metrics
- `GET /api/metrics/rag` — RAG knowledge base statistics
- `GET /api/settings` — Current model settings
- `POST /api/settings` — Update model settings

## Getting Started

### Prerequisites

- Node.js >= 18
- npm or yarn
- Deployed InsureMail AI backend (Terraform)

### Installation

```bash
cd dashboard/frontend
npm install
```

### Configuration

Create a `.env` file with your API Gateway URL:

```bash
VITE_API_BASE_URL=https://your-api-id.execute-api.us-east-1.amazonaws.com/dev
```

Get this URL from Terraform:
```bash
cd ../../terraform
terraform output api_gateway_url
```

### Development

Run the development server:

```bash
npm run dev
```

Dashboard will be available at http://localhost:3000

### Build for Production

```bash
npm run build
```

Build output will be in `dist/` directory.

## Deployment

### Option 1: Automated Script

```bash
../../scripts/deploy_dashboard.sh
```

### Option 2: Manual Deployment to S3

1. Build the application:
   ```bash
   npm run build
   ```

2. Create an S3 bucket:
   ```bash
   aws s3 mb s3://insuremail-ai-dashboard
   ```

3. Upload files:
   ```bash
   aws s3 sync dist/ s3://insuremail-ai-dashboard/ --delete
   ```

4. Enable static website hosting:
   ```bash
   aws s3 website s3://insuremail-ai-dashboard/ \
     --index-document index.html \
     --error-document index.html
   ```

5. Make bucket public (or use CloudFront):
   ```bash
   # Add bucket policy for public read access
   ```

### Option 3: CloudFront + S3

For production with custom domain and HTTPS:

1. Deploy to S3 (steps above)
2. Create CloudFront distribution
3. Point to S3 bucket
4. Add custom domain (Route 53)
5. Enable SSL certificate (ACM)

## Project Structure

```
dashboard/frontend/
├── index.html              # HTML entry point
├── package.json            # Dependencies
├── vite.config.js          # Vite configuration
├── src/
│   ├── main.jsx           # React entry point
│   ├── App.jsx            # Main app component
│   ├── App.css            # Global styles
│   ├── index.css          # Base styles
│   └── pages/             # Page components
│       ├── Dashboard.jsx     # Overview page
│       ├── EmailsList.jsx    # Email list page
│       ├── EmailDetail.jsx   # Email detail page
│       ├── ModelMetrics.jsx  # Model comparison page
│       ├── RAGMetrics.jsx    # RAG statistics page
│       └── Evaluations.jsx   # Evaluations page
└── dist/                  # Build output (gitignored)
```

## Troubleshooting

### CORS Errors

If you see CORS errors, verify:
1. API Gateway has CORS enabled
2. Lambda function returns proper CORS headers
3. `.env` file has correct API URL

### API Not Responding

Check:
1. Terraform deployment completed successfully
2. API Gateway URL is correct
3. Lambda functions are deployed
4. IAM permissions are correct

### Build Errors

Common issues:
- Node version mismatch (use Node 18+)
- Missing dependencies (run `npm install`)
- Syntax errors in code

## License

MIT
