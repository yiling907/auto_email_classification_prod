import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'

const COLORS = ['#667eea', '#764ba2', '#f093fb', '#4facfe', '#00f2fe', '#43e97b', '#fa709a']

function RAGMetrics({ apiUrl }) {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchMetrics()
  }, [])

  const fetchMetrics = async () => {
    try {
      setLoading(true)
      const response = await axios.get(`${apiUrl}/api/metrics/rag`)
      setMetrics(response.data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading RAG metrics...</div>
  if (error) return <div className="error">Error: {error}</div>
  if (!metrics) return null

  const chartData = Object.entries(metrics.by_type || {}).map(([name, value], index) => ({
    name: name.charAt(0).toUpperCase() + name.slice(1).replace('_', ' '),
    value,
    color: COLORS[index % COLORS.length]
  }))

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.75rem' }}>RAG Effectiveness Metrics</h2>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value">{metrics.total_documents}</div>
          <div className="stat-label">Total Documents</div>
        </div>

        <div className="stat-card">
          <div className="stat-value">{Object.keys(metrics.by_type || {}).length}</div>
          <div className="stat-label">Document Types</div>
        </div>

        <div className="stat-card">
          <div className="stat-value">
            <span style={{ color: metrics.status === 'active' ? '#28a745' : '#dc3545' }}>
              {metrics.status}
            </span>
          </div>
          <div className="stat-label">Knowledge Base Status</div>
        </div>
      </div>

      {chartData.length > 0 && (
        <div className="card">
          <h3 className="card-title">Documents by Type</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, value }) => `${name}: ${value}`}
                outerRadius={100}
                fill="#8884d8"
                dataKey="value"
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card">
        <h3 className="card-title">Knowledge Base Statistics</h3>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Document Type</th>
                <th>Count</th>
                <th>Percentage</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(metrics.by_type || {}).map(([type, count]) => {
                const percentage = ((count / metrics.total_documents) * 100).toFixed(1)
                return (
                  <tr key={type}>
                    <td><strong>{type.replace('_', ' ').charAt(0).toUpperCase() + type.slice(1)}</strong></td>
                    <td>{count}</td>
                    <td>{percentage}%</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">About RAG System</h3>
        <div style={{ lineHeight: '1.8' }}>
          <p style={{ marginBottom: '1rem' }}>
            The Retrieval-Augmented Generation (RAG) system uses semantic similarity search to find relevant knowledge base documents for each email.
          </p>
          <ul style={{ marginLeft: '1.5rem' }}>
            <li>Documents are chunked into 500-token segments with 50-token overlap</li>
            <li>Embeddings are generated using Amazon Titan Embeddings</li>
            <li>Semantic search returns top-3 most relevant documents</li>
            <li>Claude 3 uses these documents to generate compliant, accurate responses</li>
          </ul>
        </div>
      </div>
    </div>
  )
}

export default RAGMetrics
