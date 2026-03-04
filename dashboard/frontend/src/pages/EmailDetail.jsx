import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useParams, Link } from 'react-router-dom'

function EmailDetail({ apiUrl }) {
  const { emailId } = useParams()
  const [email, setEmail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchEmail()
  }, [emailId])

  const fetchEmail = async () => {
    try {
      setLoading(true)
      const response = await axios.get(`${apiUrl}/api/email/${emailId}`)
      setEmail(response.data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading email details...</div>
  if (error) return <div className="error">Error: {error}</div>
  if (!email) return null

  return (
    <div>
      <Link to="/emails" style={{ marginBottom: '1rem', display: 'inline-block' }}>
        ← Back to Emails
      </Link>

      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.75rem' }}>Email Details</h2>

      <div className="card">
        <h3 className="card-title">Basic Information</h3>
        <div style={{ display: 'grid', gap: '1rem' }}>
          <div>
            <strong>Email ID:</strong> <code>{email.email_id}</code>
          </div>
          <div>
            <strong>From:</strong> {email.from_address || 'N/A'}
          </div>
          <div>
            <strong>To:</strong> {email.to_address || 'N/A'}
          </div>
          <div>
            <strong>Subject:</strong> {email.subject || 'No subject'}
          </div>
          <div>
            <strong>Timestamp:</strong> {new Date(email.timestamp).toLocaleString()}
          </div>
          <div>
            <strong>Processing Status:</strong> {email.processing_status || 'unknown'}
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">Email Body</h3>
        <pre style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word', padding: '1rem', background: '#f8f9fa', borderRadius: '4px' }}>
          {email.body || 'No body content'}
        </pre>
      </div>

      <div className="card">
        <h3 className="card-title">AI Analysis</h3>
        <div style={{ display: 'grid', gap: '1rem' }}>
          <div>
            <strong>Confidence Score:</strong>
            <span style={{ marginLeft: '0.5rem' }}>
              {email.confidence_score !== undefined ? email.confidence_score.toFixed(3) : 'N/A'}
            </span>
          </div>
          <div>
            <strong>Confidence Level:</strong>
            <span style={{ marginLeft: '0.5rem' }}>
              <span className={`badge badge-${email.confidence_level}`}>
                {email.confidence_level}
              </span>
            </span>
          </div>
          <div>
            <strong>Action:</strong> {email.action || 'pending'}
          </div>
        </div>
      </div>

      {email.response_text && (
        <div className="card">
          <h3 className="card-title">Generated Response</h3>
          <div style={{ padding: '1rem', background: '#f8f9fa', borderRadius: '4px', marginTop: '1rem' }}>
            {email.response_text}
          </div>
        </div>
      )}

      <div className="card">
        <h3 className="card-title">Storage Location</h3>
        <div style={{ display: 'grid', gap: '1rem' }}>
          <div>
            <strong>S3 Bucket:</strong> <code>{email.s3_bucket || 'N/A'}</code>
          </div>
          <div>
            <strong>S3 Key:</strong> <code>{email.s3_key || 'N/A'}</code>
          </div>
        </div>
      </div>
    </div>
  )
}

export default EmailDetail
