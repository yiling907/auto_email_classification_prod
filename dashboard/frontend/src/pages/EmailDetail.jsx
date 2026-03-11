import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useParams, Link } from 'react-router-dom'

function EmailDetail({ apiUrl }) {
  const { emailId } = useParams()
  const [email, setEmail]       = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [responseText, setResponseText] = useState('')
  const [saving, setSaving]     = useState(false)
  const [sending, setSending]   = useState(false)
  const [msg, setMsg]           = useState(null)   // { type: 'success'|'error', text }

  useEffect(() => { fetchEmail() }, [emailId])

  const fetchEmail = async () => {
    try {
      setLoading(true)
      const response = await axios.get(`${apiUrl}/api/email/${emailId}`)
      setEmail(response.data)
      setResponseText(response.data.llm_response || '')
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleSaveDraft = async () => {
    setSaving(true)
    setMsg(null)
    try {
      await axios.post(`${apiUrl}/api/email/${emailId}`, { llm_response: responseText })
      setEmail(e => ({ ...e, llm_response: responseText }))
      setMsg({ type: 'success', text: 'Draft saved.' })
    } catch (err) {
      setMsg({ type: 'error', text: `Save failed: ${err.message}` })
    } finally {
      setSaving(false)
    }
  }

  const handleSend = async () => {
    if (!window.confirm(`Send this response to ${email?.sender_email}?`)) return
    setSending(true)
    setMsg(null)
    // Save current text first, then send
    try {
      await axios.post(`${apiUrl}/api/email/${emailId}`, { llm_response: responseText })
      await axios.post(`${apiUrl}/api/email/${emailId}/send`, {})
      setMsg({ type: 'success', text: `Response sent to ${email.sender_email}.` })
    } catch (err) {
      setMsg({ type: 'error', text: `Send failed: ${err.message}` })
    } finally {
      setSending(false)
    }
  }

  const formatDate = (val) => {
    if (!val) return 'N/A'
    try { return new Date(val).toLocaleString() } catch { return val }
  }

  const Field = ({ label, value }) => (
    <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: '0.5rem', padding: '0.4rem 0', borderBottom: '1px solid #f0f0f0' }}>
      <strong style={{ color: '#555' }}>{label}</strong>
      <span>{value ?? 'N/A'}</span>
    </div>
  )

  if (loading) return <div className="loading">Loading email details...</div>
  if (error)   return <div className="error">Error: {error}</div>
  if (!email)  return null

  const referenceIds = Array.isArray(email.reference_ids) ? email.reference_ids : []
  const isDirty      = responseText !== (email.llm_response || '')

  return (
    <div>
      <Link to="/emails" style={{ marginBottom: '1rem', display: 'inline-block' }}>
        ← Back to Emails
      </Link>

      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.75rem' }}>Email Details</h2>

      {/* ── Basic Info ── */}
      <div className="card">
        <h3 className="card-title">Basic Information</h3>
        <Field label="Email ID"          value={<code>{email.email_id}</code>} />
        <Field label="Thread ID"         value={email.thread_id} />
        <Field label="Message Index"     value={email.message_index} />
        <Field label="Sender Name"       value={email.sender_name} />
        <Field label="Sender Email"      value={email.sender_email} />
        <Field label="Mailbox (To)"      value={email.mailbox} />
        <Field label="Channel"           value={email.channel} />
        <Field label="Subject"           value={email.subject} />
        <Field label="Received At"       value={formatDate(email.received_at)} />
        <Field label="Detected Language" value={email.detected_language} />
        <Field label="Processing Status" value={email.processing_status} />
      </div>

      {/* ── Email Body ── */}
      <div className="card">
        <h3 className="card-title">Email Body</h3>
        <pre style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word', padding: '1rem', background: '#f8f9fa', borderRadius: '4px', margin: 0 }}>
          {email.body_text || 'No body content'}
        </pre>
      </div>

      {/* ── Classification ── */}
      <div className="card">
        <h3 className="card-title">Classification</h3>
        <Field label="Customer Intent"      value={email.customer_intent} />
        <Field label="Secondary Intent"     value={email.secondary_intent || '—'} />
        <Field label="Business Line"        value={email.business_line} />
        <Field label="Urgency"              value={email.urgency} />
        <Field label="Sentiment"            value={email.sentiment} />
        <Field label="Route Team"           value={email.gold_route_team} />
        <Field label="Priority"             value={email.gold_priority} />
        <Field label="Requires Human Review" value={String(email.requires_human_review ?? 'N/A')} />
        <Field label="Classification Time"  value={formatDate(email.classification_timestamp)} />
      </div>

      {/* ── Extracted Data ── */}
      <div className="card">
        <h3 className="card-title">Extracted Data</h3>
        <Field label="Policy Number"        value={email.policy_number} />
        <Field label="Member ID"            value={email.member_id} />
        <Field label="Customer ID"          value={email.customer_id} />
        <Field label="Has Attachment"       value={String(email.has_attachment ?? 'N/A')} />
        <Field label="Attachment Count"     value={email.attachment_count} />
        <Field label="Medical Terms Present" value={String(email.medical_terms_present ?? 'N/A')} />
        <Field label="PII Present"          value={String(email.pii_present ?? 'N/A')} />
      </div>

      {/* ── AI Decision ── */}
      <div className="card">
        <h3 className="card-title">AI Decision</h3>
        <Field label="Confidence Score" value={
          email.confidence_score !== undefined
            ? parseFloat(email.confidence_score).toFixed(4)
            : 'N/A'
        } />
        <Field label="Confidence Level" value={
          <span className={`badge badge-${email.confidence_level}`}>{email.confidence_level || 'N/A'}</span>
        } />
        <Field label="Action"           value={email.action} />
        <Field label="Response Time"    value={formatDate(email.response_timestamp)} />
      </div>

      {/* ── LLM Response (editable) ── */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 className="card-title" style={{ margin: 0 }}>Generated Response</h3>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            {isDirty && (
              <span style={{ fontSize: '0.8rem', color: '#856404', background: '#fff3cd', padding: '2px 8px', borderRadius: 4 }}>
                Unsaved changes
              </span>
            )}
            <button
              onClick={handleSaveDraft}
              disabled={saving || !isDirty}
              className="btn"
              style={{ background: '#6c757d', color: '#fff', opacity: (!isDirty || saving) ? 0.5 : 1 }}
            >
              {saving ? 'Saving…' : 'Save Draft'}
            </button>
            <button
              onClick={handleSend}
              disabled={sending || !email.sender_email || !responseText}
              className="btn btn-primary"
              style={{ opacity: (sending || !email.sender_email || !responseText) ? 0.5 : 1 }}
            >
              {sending ? 'Sending…' : `Send to ${email.sender_email || 'sender'}`}
            </button>
          </div>
        </div>

        {msg && (
          <div style={{
            marginBottom: '0.75rem',
            padding: '0.6rem 1rem',
            borderRadius: 4,
            background: msg.type === 'success' ? '#d4edda' : '#f8d7da',
            color:      msg.type === 'success' ? '#155724' : '#721c24',
            fontSize: '0.9rem',
          }}>
            {msg.text}
          </div>
        )}

        <textarea
          value={responseText}
          onChange={e => setResponseText(e.target.value)}
          rows={14}
          style={{
            width: '100%',
            fontFamily: 'inherit',
            fontSize: '0.9rem',
            lineHeight: 1.6,
            padding: '0.75rem',
            border: '1px solid #ced4da',
            borderRadius: 4,
            resize: 'vertical',
            boxSizing: 'border-box',
          }}
          placeholder="No response generated yet."
        />

        {referenceIds.length > 0 && (
          <div style={{ marginTop: '0.75rem' }}>
            <strong style={{ fontSize: '0.85rem' }}>Reference Documents:</strong>
            <ul style={{ margin: '0.4rem 0 0 1.5rem', fontSize: '0.85rem' }}>
              {referenceIds.map((id, i) => <li key={i}><code>{id}</code></li>)}
            </ul>
          </div>
        )}
      </div>

      {/* ── Storage ── */}
      <div className="card">
        <h3 className="card-title">Storage</h3>
        <Field label="S3 Bucket" value={<code>{email.s3_bucket}</code>} />
        <Field label="S3 Key"    value={<code>{email.s3_key}</code>} />
      </div>
    </div>
  )
}

export default EmailDetail
