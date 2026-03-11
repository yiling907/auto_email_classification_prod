import React, { useState, useEffect } from 'react'
import axios from 'axios'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from 'recharts'

const TASK_LABELS = {
  email_classification: 'Intent Classification',
  accuracy_evaluation:  'Classification Accuracy (judge)',
  response_generation:  'Response Generation',
  response_evaluation:  'Response Evaluation (judge)',
}

const MODEL_COLORS = {
  'mistral-7b':   '#667eea',
  'llama-3.1-8b': '#f093fb',
}

const ACCURACY_FIELDS = [
  'customer_intent', 'secondary_intent', 'business_line',
  'urgency', 'sentiment', 'gold_route_team', 'gold_priority',
]

const EVAL_DIMS = [
  'faithfulness', 'answer_relevance', 'context_precision', 'context_recall',
  'completeness', 'helpfulness', 'safety_compliance', 'no_harmful_advice',
]

function ScoreBar({ value, max = 1, color = '#28a745' }) {
  const pct = Math.round((value / max) * 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, background: '#e9ecef', borderRadius: 4, height: 10, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, background: color, height: '100%', borderRadius: 4, transition: 'width 0.4s' }} />
      </div>
      <span style={{ width: 40, textAlign: 'right', fontSize: '0.8rem', color: '#555' }}>
        {(value * 100).toFixed(0)}%
      </span>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="card">
      <h3 className="card-title">{title}</h3>
      {children}
    </div>
  )
}

function ModelMetrics({ apiUrl }) {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [activeTab, setActiveTab] = useState('overview')

  useEffect(() => { fetchMetrics() }, [])

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
  if (error)   return <div className="error">Error: {error}</div>
  if (!metrics) return <div className="loading">No metrics available</div>

  const { total_records, by_task, by_model, records } = metrics

  // Chart: latency by task
  const latencyChartData = Object.entries(by_task).map(([tt, s]) => ({
    name: TASK_LABELS[tt] || tt,
    'Avg Latency (ms)': s.avg_latency_ms,
  }))

  // Chart: cost by task
  const costChartData = Object.entries(by_task).map(([tt, s]) => ({
    name: TASK_LABELS[tt] || tt,
    'Total Cost ($)': s.total_cost_usd,
    'Avg Cost ($)':   s.avg_cost_usd,
  }))

  // Radar: accuracy field scores
  const accTask   = by_task['accuracy_evaluation'] || {}
  const radarAccuracy = ACCURACY_FIELDS.map(f => ({
    field: f.replace(/_/g, ' '),
    score: Math.round(((accTask.avg_field_accuracy || {})[f] || 0) * 100),
  }))

  // Radar: eval dimension scores
  const evalTask   = by_task['response_evaluation'] || {}
  const radarEval  = EVAL_DIMS.map(d => ({
    dim: d.replace(/_/g, ' '),
    score: Math.round(((evalTask.avg_eval_scores || {})[d] || 0) * 100),
  }))

  const tabs = [
    { key: 'overview',  label: 'Overview' },
    { key: 'accuracy',  label: 'Classification Accuracy' },
    { key: 'response',  label: 'Response Quality' },
    { key: 'records',   label: `All Records (${total_records})` },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.75rem' }}>Model Performance</h2>

      {/* ── Top stats ── */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value">{total_records}</div>
          <div className="stat-label">Total Metric Records</div>
        </div>
        {Object.entries(by_model).map(([mn, s]) => (
          <div key={mn} className="stat-card">
            <div className="stat-value" style={{ fontSize: '1.1rem', color: MODEL_COLORS[mn] || '#667eea' }}>
              {mn}
            </div>
            <div style={{ fontSize: '0.85rem', marginTop: 4 }}>
              <div>{s.count} calls · ${s.total_cost_usd.toFixed(4)} total</div>
              <div style={{ color: '#7f8c8d' }}>avg {s.avg_latency_ms.toFixed(0)} ms</div>
            </div>
          </div>
        ))}
      </div>

      {/* ── Tabs ── */}
      <div style={{ display: 'flex', gap: 4, marginBottom: '1rem', borderBottom: '2px solid #e9ecef', paddingBottom: 0 }}>
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            style={{
              padding: '0.5rem 1rem',
              border: 'none',
              background: 'none',
              cursor: 'pointer',
              fontWeight: activeTab === t.key ? 700 : 400,
              color:      activeTab === t.key ? '#007bff' : '#555',
              borderBottom: activeTab === t.key ? '2px solid #007bff' : '2px solid transparent',
              marginBottom: -2,
              fontSize: '0.9rem',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Overview tab ── */}
      {activeTab === 'overview' && (
        <>
          {/* Per-task summary cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
            {Object.entries(by_task).map(([tt, s]) => (
              <div key={tt} style={{ background: '#fff', border: '1px solid #dee2e6', borderRadius: 8, padding: '1rem' }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>{TASK_LABELS[tt] || tt}</div>
                <div style={{ fontSize: '0.8rem', color: '#6c757d', marginBottom: 8 }}>
                  Model: <span style={{ color: MODEL_COLORS[s.models?.[0]] || '#555', fontWeight: 600 }}>
                    {s.models?.join(', ') || 'unknown'}
                  </span>
                </div>
                <div style={{ fontSize: '0.85rem', display: 'grid', gap: 3 }}>
                  <div>Calls: <strong>{s.count}</strong></div>
                  <div>Avg latency: <strong>{s.avg_latency_ms.toFixed(0)} ms</strong></div>
                  <div>Avg cost: <strong>${s.avg_cost_usd.toFixed(6)}</strong></div>
                  <div>Total cost: <strong>${s.total_cost_usd.toFixed(4)}</strong></div>
                  {s.avg_overall_accuracy !== undefined && (
                    <div>Avg accuracy: <strong>{(s.avg_overall_accuracy * 100).toFixed(1)}%</strong></div>
                  )}
                  {s.avg_confidence_score !== undefined && (
                    <div>Avg confidence: <strong>{(s.avg_confidence_score * 100).toFixed(1)}%</strong></div>
                  )}
                </div>
              </div>
            ))}
          </div>

          <Section title="Average Latency by Task (ms)">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={latencyChartData} margin={{ left: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis />
                <Tooltip formatter={v => `${v.toFixed(0)} ms`} />
                <Bar dataKey="Avg Latency (ms)" fill="#667eea" radius={[4,4,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </Section>

          <Section title="Cost by Task">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={costChartData} margin={{ left: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={v => `$${v.toFixed(4)}`} />
                <Tooltip formatter={v => `$${v.toFixed(6)}`} />
                <Legend />
                <Bar dataKey="Total Cost ($)" fill="#f093fb" radius={[4,4,0,0]} />
                <Bar dataKey="Avg Cost ($)"   fill="#4facfe" radius={[4,4,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </Section>
        </>
      )}

      {/* ── Classification Accuracy tab ── */}
      {activeTab === 'accuracy' && (
        <>
          <Section title={`Classification Accuracy  —  ${TASK_LABELS['accuracy_evaluation']}`}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
              <div>
                <div style={{ marginBottom: '0.5rem', fontWeight: 600 }}>Summary</div>
                <div style={{ fontSize: '0.9rem', display: 'grid', gap: 6 }}>
                  <div>Records: <strong>{accTask.count ?? 0}</strong></div>
                  <div>Judge model: <strong>{accTask.models?.join(', ') || '—'}</strong></div>
                  <div>Avg overall accuracy: <strong style={{ fontSize: '1.1rem', color: '#28a745' }}>
                    {accTask.avg_overall_accuracy !== undefined
                      ? `${(accTask.avg_overall_accuracy * 100).toFixed(1)}%` : '—'}
                  </strong></div>
                  <div>Avg latency: <strong>{accTask.avg_latency_ms?.toFixed(0) ?? '—'} ms</strong></div>
                  <div>Total cost: <strong>${accTask.total_cost_usd?.toFixed(4) ?? '—'}</strong></div>
                </div>
              </div>
              <div>
                <div style={{ marginBottom: '0.5rem', fontWeight: 600 }}>Per-Field Accuracy</div>
                {ACCURACY_FIELDS.map(f => {
                  const val = (accTask.avg_field_accuracy || {})[f] ?? null
                  return (
                    <div key={f} style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: '0.8rem', marginBottom: 3, color: '#555', textTransform: 'capitalize' }}>
                        {f.replace(/_/g, ' ')}
                      </div>
                      {val !== null
                        ? <ScoreBar value={val} color={val >= 0.8 ? '#28a745' : val >= 0.5 ? '#ffc107' : '#dc3545'} />
                        : <span style={{ fontSize: '0.75rem', color: '#aaa' }}>no data</span>}
                    </div>
                  )
                })}
              </div>
            </div>
          </Section>

          {radarAccuracy.some(r => r.score > 0) && (
            <Section title="Field Accuracy Radar">
              <ResponsiveContainer width="100%" height={320}>
                <RadarChart data={radarAccuracy}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="field" tick={{ fontSize: 11 }} />
                  <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 10 }} />
                  <Radar name="Accuracy %" dataKey="score" stroke="#667eea" fill="#667eea" fillOpacity={0.4} />
                  <Tooltip formatter={v => `${v}%`} />
                </RadarChart>
              </ResponsiveContainer>
            </Section>
          )}
        </>
      )}

      {/* ── Response Quality tab ── */}
      {activeTab === 'response' && (
        <>
          <Section title={`Response Quality  —  ${TASK_LABELS['response_evaluation']}`}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
              <div>
                <div style={{ marginBottom: '0.5rem', fontWeight: 600 }}>Summary</div>
                <div style={{ fontSize: '0.9rem', display: 'grid', gap: 6 }}>
                  <div>Records: <strong>{evalTask.count ?? 0}</strong></div>
                  <div>Judge model: <strong>{evalTask.models?.join(', ') || '—'}</strong></div>
                  <div>Avg confidence score: <strong style={{ fontSize: '1.1rem', color: '#28a745' }}>
                    {evalTask.avg_confidence_score !== undefined
                      ? `${(evalTask.avg_confidence_score * 100).toFixed(1)}%` : '—'}
                  </strong></div>
                  <div>Avg latency: <strong>{evalTask.avg_latency_ms?.toFixed(0) ?? '—'} ms</strong></div>
                  <div>Total cost: <strong>${evalTask.total_cost_usd?.toFixed(4) ?? '—'}</strong></div>
                </div>
              </div>
              <div>
                <div style={{ marginBottom: '0.5rem', fontWeight: 600 }}>Per-Dimension Scores</div>
                {EVAL_DIMS.map(d => {
                  const val = (evalTask.avg_eval_scores || {})[d] ?? null
                  return (
                    <div key={d} style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: '0.8rem', marginBottom: 3, color: '#555', textTransform: 'capitalize' }}>
                        {d.replace(/_/g, ' ')}
                      </div>
                      {val !== null
                        ? <ScoreBar value={val} color={val >= 0.8 ? '#28a745' : val >= 0.5 ? '#ffc107' : '#dc3545'} />
                        : <span style={{ fontSize: '0.75rem', color: '#aaa' }}>no data</span>}
                    </div>
                  )
                })}
              </div>
            </div>
          </Section>

          {radarEval.some(r => r.score > 0) && (
            <Section title="Quality Dimension Radar">
              <ResponsiveContainer width="100%" height={320}>
                <RadarChart data={radarEval}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="dim" tick={{ fontSize: 11 }} />
                  <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 10 }} />
                  <Radar name="Score %" dataKey="score" stroke="#f093fb" fill="#f093fb" fillOpacity={0.4} />
                  <Tooltip formatter={v => `${v}%`} />
                </RadarChart>
              </ResponsiveContainer>
            </Section>
          )}
        </>
      )}

      {/* ── All Records tab ── */}
      {activeTab === 'records' && (
        <Section title="All Metric Records">
          <div className="table-container" style={{ overflowX: 'auto' }}>
            <table style={{ minWidth: 900 }}>
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Task Type</th>
                  <th>Model</th>
                  <th>Email ID</th>
                  <th style={{ textAlign: 'right' }}>Latency (ms)</th>
                  <th style={{ textAlign: 'right' }}>Cost ($)</th>
                  <th style={{ textAlign: 'right' }}>Score</th>
                </tr>
              </thead>
              <tbody>
                {records.map(r => {
                  const score =
                    r.task_type === 'accuracy_evaluation'  ? r.overall_accuracy :
                    r.task_type === 'response_evaluation'  ? r.confidence_score : null
                  return (
                    <tr key={r.metric_key}>
                      <td style={{ whiteSpace: 'nowrap', fontSize: '0.8rem' }}>
                        {r.timestamp ? new Date(r.timestamp).toLocaleString() : '—'}
                      </td>
                      <td><span style={{ fontSize: '0.8rem', background: '#e9ecef', padding: '2px 6px', borderRadius: 4 }}>
                        {r.task_type}
                      </span></td>
                      <td style={{ color: MODEL_COLORS[r.model_name] || '#555', fontWeight: 600, fontSize: '0.85rem' }}>
                        {r.model_name}
                      </td>
                      <td><code style={{ fontSize: '0.75rem' }}>{(r.email_id || '').substring(0, 12)}…</code></td>
                      <td style={{ textAlign: 'right' }}>{parseFloat(r.latency_ms || 0).toFixed(0)}</td>
                      <td style={{ textAlign: 'right' }}>${parseFloat(r.cost_usd || 0).toFixed(6)}</td>
                      <td style={{ textAlign: 'right' }}>
                        {score !== undefined && score !== null
                          ? <span style={{
                              color: parseFloat(score) >= 0.8 ? '#28a745' : parseFloat(score) >= 0.5 ? '#856404' : '#dc3545',
                              fontWeight: 600,
                            }}>
                              {(parseFloat(score) * 100).toFixed(1)}%
                            </span>
                          : <span style={{ color: '#aaa' }}>—</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  )
}

export default ModelMetrics
