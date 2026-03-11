import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Link } from 'react-router-dom'

const ACTION_OPTIONS    = ['all', 'auto_response', 'human_review', 'escalate']
const CONFIDENCE_OPTIONS = ['all', 'high', 'medium', 'low', 'pending']
const STATUS_OPTIONS    = ['all', 'completed', 'parsed', 'processing', 'error']

function EmailsList({ apiUrl }) {
  const [emails, setEmails]   = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [filters, setFilters] = useState({ confidence_level: 'all', action: 'all', processing_status: 'all' })

  useEffect(() => { fetchEmails() }, [filters])

  const fetchEmails = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      Object.entries(filters).forEach(([k, v]) => { if (v !== 'all') params.append(k, v) })
      const url = `${apiUrl}/api/emails${params.toString() ? '?' + params.toString() : ''}`
      const response = await axios.get(url)
      setEmails(response.data.emails || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const setFilter = (key, value) => setFilters(f => ({ ...f, [key]: value }))

  const formatDate = (val) => {
    if (!val) return 'N/A'
    try { return new Date(val).toLocaleString() } catch { return val }
  }

  const selectStyle = { padding: '0.4rem 0.6rem', borderRadius: 4, border: '1px solid #ddd', fontSize: '0.85rem' }

  if (loading) return <div className="loading">Loading emails...</div>
  if (error)   return <div className="error">Error: {error}</div>

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <h2 style={{ fontSize: '1.75rem', margin: 0 }}>Email Processing History</h2>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <div>
            <label style={{ fontSize: '0.8rem', color: '#6c757d', marginRight: 4 }}>Confidence</label>
            <select value={filters.confidence_level} onChange={e => setFilter('confidence_level', e.target.value)} style={selectStyle}>
              {CONFIDENCE_OPTIONS.map(o => <option key={o} value={o}>{o === 'all' ? 'All Confidence' : o.charAt(0).toUpperCase() + o.slice(1)}</option>)}
            </select>
          </div>
          <div>
            <label style={{ fontSize: '0.8rem', color: '#6c757d', marginRight: 4 }}>Action</label>
            <select value={filters.action} onChange={e => setFilter('action', e.target.value)} style={selectStyle}>
              {ACTION_OPTIONS.map(o => <option key={o} value={o}>{o === 'all' ? 'All Actions' : o.replace('_', ' ')}</option>)}
            </select>
          </div>
          <div>
            <label style={{ fontSize: '0.8rem', color: '#6c757d', marginRight: 4 }}>Status</label>
            <select value={filters.processing_status} onChange={e => setFilter('processing_status', e.target.value)} style={selectStyle}>
              {STATUS_OPTIONS.map(o => <option key={o} value={o}>{o === 'all' ? 'All Statuses' : o.charAt(0).toUpperCase() + o.slice(1)}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="card">
        <div style={{ marginBottom: '0.5rem', fontSize: '0.85rem', color: '#6c757d' }}>
          {emails.length} email{emails.length !== 1 ? 's' : ''} found
        </div>
        <div className="table-container" style={{ overflowX: 'auto' }}>
          <table style={{ minWidth: '1100px' }}>
            <thead>
              <tr>
                <th>Email ID</th>
                <th>Sender</th>
                <th>Subject</th>
                <th>Received</th>
                <th>Intent</th>
                <th>Urgency</th>
                <th>Sentiment</th>
                <th>Route Team</th>
                <th>Confidence</th>
                <th>Action</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {emails.length === 0 ? (
                <tr>
                  <td colSpan="12" style={{ textAlign: 'center', padding: '2rem', color: '#7f8c8d' }}>
                    No emails match the selected filters
                  </td>
                </tr>
              ) : (
                emails.map((email) => (
                  <tr key={email.email_id}>
                    <td><code>{email.email_id.substring(0, 8)}...</code></td>
                    <td>
                      <div>{email.sender_name || 'N/A'}</div>
                      <div style={{ fontSize: '0.75rem', color: '#7f8c8d' }}>{email.sender_email || ''}</div>
                    </td>
                    <td>{email.subject || 'No subject'}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{formatDate(email.received_at)}</td>
                    <td>{email.customer_intent || 'N/A'}</td>
                    <td>{email.urgency || 'N/A'}</td>
                    <td>{email.sentiment || 'N/A'}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{email.gold_route_team || 'N/A'}</td>
                    <td>
                      <span className={`badge badge-${email.confidence_level}`}>
                        {email.confidence_level || 'pending'}
                      </span>
                      {email.confidence_score !== undefined && (
                        <div style={{ fontSize: '0.75rem', color: '#7f8c8d' }}>
                          {parseFloat(email.confidence_score).toFixed(2)}
                        </div>
                      )}
                    </td>
                    <td>{email.action || 'pending'}</td>
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
