# InsureMail AI Dashboard

Modern React-based dashboard for monitoring and managing the InsureMail AI email processing system.

## Features

### 📊 Dashboard Overview
- Total emails processed
- Average confidence score
- Auto-response rate
- Confidence distribution visualization
- Recent emails list

### 📧 Email Management
- Browse all processed emails
- Filter by confidence level
- View detailed email trace
- See AI-generated responses
- Track processing status

### 📈 Model Performance
- Compare multiple LLM models
- View latency, cost, and success rates
- Interactive charts and metrics
- Detailed statistics table

### 🔍 RAG Effectiveness
- Knowledge base statistics
- Document type distribution
- System status monitoring

## Technology Stack

- **Frontend Framework**: React 18
- **Build Tool**: Vite
- **Routing**: React Router DOM
- **Charts**: Recharts
- **HTTP Client**: Axios
- **Styling**: Custom CSS

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
│       └── RAGMetrics.jsx    # RAG statistics page
└── dist/                  # Build output (gitignored)
```

## API Endpoints Used

The dashboard consumes the following API endpoints:

- `GET /api/dashboard/overview` - Dashboard statistics
- `GET /api/emails` - List of emails
- `GET /api/emails?confidence_level={level}` - Filtered emails
- `GET /api/email/{emailId}` - Email details
- `GET /api/metrics/models` - Model performance metrics
- `GET /api/metrics/rag` - RAG effectiveness metrics

## Customization

### Adding New Pages

1. Create component in `src/pages/`
2. Add route in `src/App.jsx`
3. Add navigation link in navbar

### Modifying Styles

- Global styles: `src/index.css`
- App-wide styles: `src/App.css`
- Component-specific: Inline or separate CSS file

### Adding Charts

Using Recharts library:

```jsx
import { BarChart, Bar, XAxis, YAxis } from 'recharts'

<BarChart data={data}>
  <Bar dataKey="value" fill="#667eea" />
</BarChart>
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

## Performance Optimization

- React.memo for expensive components
- Lazy loading for routes
- Image optimization
- Code splitting with Vite
- CDN delivery (CloudFront)

## Security

- No sensitive data in frontend code
- API authentication (add when needed)
- HTTPS only in production
- CSP headers recommended
- Regular dependency updates

## License

MIT
