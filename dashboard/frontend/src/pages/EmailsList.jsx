import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Link } from 'react-router-dom'

function EmailsList({ apiUrl }) {
  const [emails, setEmails] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('all')

  useEffect(() => {
    fetchEmails()
  }, [filter])

  const fetchEmails = async () => {
    try {
      setLoading(true)
      const url = filter === 'all'
        ? `${apiUrl}/api/emails`
        : `${apiUrl}/api/emails?confidence_level=${filter}`

      const response = await axios.get(url)
      setEmails(response.data.emails || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading emails...</div>
  if (error) return <div className="error">Error: {error}</div>

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.75rem' }}>Email Processing History</h2>
        <div>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ padding: '0.5rem', borderRadius: '4px', border: '1px solid #ddd' }}
          >
            <option value="all">All Confidence Levels</option>
            <option value="high">High Confidence</option>
            <option value="medium">Medium Confidence</option>
            <option value="low">Low Confidence</option>
            <option value="pending">Pending</option>
          </select>
        </div>
      </div>

      <div className="card">
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Email ID</th>
                <th>From</th>
                <th>Subject</th>
                <th>Timestamp</th>
                <th>Confidence</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {emails.length === 0 ? (
                <tr>
                  <td colSpan="7" style={{ textAlign: 'center', padding: '2rem', color: '#7f8c8d' }}>
                    No emails found
                  </td>
                </tr>
              ) : (
                emails.map((email) => (
                  <tr key={email.email_id}>
                    <td><code>{email.email_id.substring(0, 8)}...</code></td>
                    <td>{email.from_address || 'N/A'}</td>
                    <td>{email.subject || 'No subject'}</td>
                    <td>{new Date(email.timestamp).toLocaleString()}</td>
                    <td>
                      <span className={`badge badge-${email.confidence_level}`}>
                        {email.confidence_level}
                      </span>
                    </td>
                    <td>{email.processing_status || 'unknown'}</td>
                    <td>
                      <Link to={`/email/${email.email_id}`} className="btn btn-primary">
                        Details
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default EmailsList
