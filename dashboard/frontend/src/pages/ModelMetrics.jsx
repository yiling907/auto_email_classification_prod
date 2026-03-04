import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

function ModelMetrics({ apiUrl }) {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchMetrics()
  }, [])

  const fetchMetrics = async () => {
    try {
      setLoading(true)
      const response = await axios.get(`${apiUrl}/api/metrics/models`)
      setMetrics(response.data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading model metrics...</div>
  if (error) return <div className="error">Error: {error}</div>
  if (!metrics || !metrics.by_model) return <div className="loading">No metrics available</div>

  const chartData = Object.entries(metrics.by_model).map(([name, stats]) => ({
    name,
    latency: stats.avg_latency_ms,
    cost: stats.avg_cost_usd * 1000, // Convert to micro-dollars for readability
    successRate: stats.success_rate
  }))

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.75rem' }}>Model Performance Metrics</h2>

      <div className="stats-grid">
        {Object.entries(metrics.by_model).map(([modelName, stats]) => (
          <div key={modelName} className="stat-card">
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', marginBottom: '0.5rem', color: '#667eea' }}>
              {modelName}
            </div>
            <div style={{ color: '#7f8c8d', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              {stats.total_requests} requests
            </div>
            <div style={{ fontSize: '0.875rem' }}>
              <div>Success: {stats.success_rate}%</div>
              <div>Avg Latency: {stats.avg_latency_ms.toFixed(0)}ms</div>
              <div>Avg Cost: ${stats.avg_cost_usd.toFixed(6)}</div>
            </div>
          </div>
        ))}
      </div>

      {chartData.length > 0 && (
        <>
          <div className="card">
            <h3 className="card-title">Average Latency by Model (ms)</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="latency" fill="#667eea" name="Latency (ms)" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="card">
            <h3 className="card-title">Success Rate by Model (%)</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis domain={[0, 100]} />
                <Tooltip />
                <Legend />
                <Bar dataKey="successRate" fill="#28a745" name="Success Rate (%)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      <div className="card">
        <h3 className="card-title">Detailed Model Statistics</h3>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Total Requests</th>
                <th>Successful</th>
                <th>Success Rate</th>
                <th>Avg Latency</th>
                <th>Total Cost</th>
                <th>Avg Cost</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(metrics.by_model).map(([modelName, stats]) => (
                <tr key={modelName}>
                  <td><strong>{modelName}</strong></td>
                  <td>{stats.total_requests}</td>
                  <td>{stats.successful_requests}</td>
                  <td>{stats.success_rate}%</td>
                  <td>{stats.avg_latency_ms.toFixed(0)}ms</td>
                  <td>${stats.total_cost_usd.toFixed(4)}</td>
                  <td>${stats.avg_cost_usd.toFixed(6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default ModelMetrics
