import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Link } from 'react-router-dom'
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'

const COLORS = {
  high: '#28a745',
  medium: '#ffc107',
  low: '#dc3545',
  pending: '#17a2b8'
}

function Dashboard({ apiUrl }) {
  const [overview, setOverview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchOverview()
  }, [])

  const fetchOverview = async () => {
    try {
      setLoading(true)
      const response = await axios.get(`${apiUrl}/api/dashboard/overview`)
      setOverview(response.data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading dashboard...</div>
  if (error) return <div className="error">Error: {error}</div>
  if (!overview) return null

  const chartData = Object.entries(overview.confidence_distribution).map(([name, value]) => ({
    name: name.charAt(0).toUpperCase() + name.slice(1),
    value,
    color: COLORS[name]
  }))

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.75rem' }}>Dashboard Overview</h2>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value">{overview.total_emails}</div>
          <div className="stat-label">Total Emails</div>
        </div>

        <div className="stat-card">
          <div className="stat-value">{overview.avg_confidence.toFixed(2)}</div>
          <div className="stat-label">Avg Confidence Score</div>
        </div>

        <div className="stat-card">
          <div className="stat-value">{overview.auto_response_rate.toFixed(1)}%</div>
          <div className="stat-label">Auto-Response Rate</div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">Confidence Distribution</h3>
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

      <div className="card">
        <h3 className="card-title">Recent Emails</h3>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Subject</th>
                <th>Timestamp</th>
                <th>Confidence</th>
                <th>Action</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {overview.recent_emails.map((email) => (
                <tr key={email.email_id}>
                  <td>{email.subject}</td>
                  <td>{new Date(email.timestamp).toLocaleString()}</td>
                  <td>
                    <span className={`badge badge-${email.confidence_level}`}>
                      {email.confidence_level}
                    </span>
                  </td>
                  <td>{email.action || 'pending'}</td>
                  <td>
                    <Link to={`/email/${email.email_id}`} className="btn btn-primary">
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
