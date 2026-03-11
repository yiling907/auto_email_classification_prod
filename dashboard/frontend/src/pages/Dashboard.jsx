import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'

const COLORS = {
  high: '#28a745',
  medium: '#ffc107',
  low: '#dc3545',
  pending: '#17a2b8'
}

const MODEL_LABELS = {
  'mistral-7b':   'Mistral 7B',
  'llama-3.1-8b': 'Llama 3.1 8B',
}

const FUNCTION_LABELS = {
  classify_intent: 'Intent Classification',
  claude_response: 'Response Generation',
}

function Toggle({ checked, onChange, disabled }) {
  return (
    <button
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        width: 52,
        height: 28,
        borderRadius: 14,
        border: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer',
        background: checked ? '#007bff' : '#ced4da',
        transition: 'background 0.2s',
        padding: 0,
        flexShrink: 0,
      }}
    >
      <span style={{
        position: 'absolute',
        width: 22,
        height: 22,
        borderRadius: '50%',
        background: '#fff',
        left: checked ? 27 : 3,
        transition: 'left 0.2s',
        boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
      }} />
    </button>
  )
}

function Dashboard({ apiUrl }) {
  const [overview, setOverview]     = useState(null)
  const [settings, setSettings]     = useState(null)   // { classify_intent: 'mistral-7b', claude_response: 'mistral-7b' }
  const [saving, setSaving]         = useState({})     // { fnKey: true/false }
  const [settingsMsg, setSettingsMsg] = useState(null)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)

  useEffect(() => {
    Promise.all([fetchOverview(), fetchSettings()])
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

  const fetchSettings = async () => {
    try {
      const response = await axios.get(`${apiUrl}/api/settings`)
      setSettings(response.data.settings)
    } catch (err) {
      console.error('Failed to load settings:', err.message)
    }
  }

  // Toggle between the two models for a given function key
  const handleToggle = async (fnKey, currentModel) => {
    const nextModel = currentModel === 'mistral-7b' ? 'llama-3.1-8b' : 'mistral-7b'
    setSaving(s => ({ ...s, [fnKey]: true }))
    setSettingsMsg(null)
    try {
      await axios.post(`${apiUrl}/api/settings`, { [fnKey]: nextModel })
      setSettings(s => ({ ...s, [fnKey]: nextModel }))
      setSettingsMsg({ type: 'success', text: `${FUNCTION_LABELS[fnKey]} switched to ${MODEL_LABELS[nextModel]}` })
    } catch (err) {
      setSettingsMsg({ type: 'error', text: `Failed to update: ${err.message}` })
    } finally {
      setSaving(s => ({ ...s, [fnKey]: false }))
    }
  }

  if (loading) return <div className="loading">Loading dashboard...</div>
  if (error)   return <div className="error">Error: {error}</div>
  if (!overview) return null

  const chartData = Object.entries(overview.confidence_distribution).map(([name, value]) => ({
    name: name.charAt(0).toUpperCase() + name.slice(1),
    value,
    color: COLORS[name]
  }))

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.75rem' }}>Dashboard Overview</h2>

      {/* ── Stats ── */}
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

      {/* ── Confidence Distribution ── */}
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

      {/* ── Model Settings ── */}
      <div className="card">
        <h3 className="card-title">Model Settings</h3>
        <p style={{ color: '#6c757d', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
          Toggle the active model for each pipeline stage. Changes take effect on the next invocation.
        </p>

        {settingsMsg && (
          <div style={{
            marginBottom: '1rem',
            padding: '0.75rem 1rem',
            borderRadius: 4,
            background: settingsMsg.type === 'success' ? '#d4edda' : '#f8d7da',
            color:      settingsMsg.type === 'success' ? '#155724' : '#721c24',
            fontSize: '0.9rem',
          }}>
            {settingsMsg.text}
          </div>
        )}

        {settings === null ? (
          <div style={{ color: '#6c757d' }}>Loading settings...</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {Object.entries(FUNCTION_LABELS).map(([fnKey, label]) => {
              const model    = settings[fnKey] || 'mistral-7b'
              const isLlama  = model === 'llama-3.1-8b'
              const isSaving = !!saving[fnKey]

              return (
                <div key={fnKey} style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '1rem 1.25rem',
                  border: '1px solid #dee2e6',
                  borderRadius: 8,
                  background: '#fafafa',
                }}>
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: 2 }}>{label}</div>
                    <div style={{ fontSize: '0.8rem', color: '#6c757d' }}>
                      Lambda: <code style={{ fontSize: '0.8rem' }}>
                        {fnKey === 'classify_intent'
                          ? 'insuremail-ai-dev-multi-llm-inference'
                          : 'insuremail-ai-dev-claude-response'}
                      </code>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <span style={{
                      fontWeight: isLlama ? 400 : 600,
                      color:      isLlama ? '#6c757d' : '#212529',
                      fontSize: '0.9rem',
                    }}>
                      Mistral 7B
                    </span>

                    <Toggle
                      checked={isLlama}
                      onChange={() => handleToggle(fnKey, model)}
                      disabled={isSaving}
                    />

                    <span style={{
                      fontWeight: isLlama ? 600 : 400,
                      color:      isLlama ? '#212529' : '#6c757d',
                      fontSize: '0.9rem',
                    }}>
                      Llama 3.1 8B
                    </span>

                    {isSaving && (
                      <span style={{ fontSize: '0.8rem', color: '#6c757d' }}>Saving…</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default Dashboard
