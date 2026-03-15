import React, { useState, useEffect } from 'react'
import axios from 'axios'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts'

const PCT = v => v != null ? `${(v * 100).toFixed(1)}%` : '—'
const FMT = v => v != null ? v.toFixed(4) : '—'

const SEVERITY_STYLE = {
  HIGH:   { background: '#f8d7da', color: '#721c24' },
  MEDIUM: { background: '#fff3cd', color: '#856404' },
  LOW:    { background: '#d4edda', color: '#155724' },
}

const DIMENSION_LABELS = {
  intent_classification:  'Intent Classification',
  routing_accuracy:       'Routing Accuracy',
  entity_extraction:      'Entity Extraction',
  rag_retrieval:          'RAG Retrieval',
  response_quality:       'Response Quality',
  confidence_calibration: 'Confidence Calibration',
}

function scoreToPct(dim, dims) {
  switch (dim) {
    case 'intent_classification':  return (dims[dim]?.accuracy ?? 0) * 100
    case 'routing_accuracy':       return (dims[dim]?.routing_accuracy ?? 0) * 100
    case 'entity_extraction':      return (dims[dim]?.policy_number?.f1 ?? 0) * 100
    case 'rag_retrieval':          return (dims[dim]?.hit_rate ?? 0) * 100
    case 'response_quality':       return (dims[dim]?.escalation_agreement ?? dims[dim]?.hedge_rate ?? 0) * 100
    case 'confidence_calibration': return Math.max(0, (1 - (dims[dim]?.ece ?? 1))) * 100
    default: return 0
  }
}

function DimensionCard({ dimKey, dims }) {
  const label = DIMENSION_LABELS[dimKey] || dimKey
  const pct   = scoreToPct(dimKey, dims)
  const color = pct >= 80 ? '#28a745' : pct >= 60 ? '#f39c12' : '#dc3545'
  const d     = dims[dimKey] || {}

  const details = []
  if (dimKey === 'intent_classification') {
    details.push(`Accuracy: ${PCT(d.accuracy)}`, `Macro F1: ${PCT(d.macro_f1)}`, `Samples: ${d.n_samples ?? '—'}`)
  } else if (dimKey === 'routing_accuracy') {
    details.push(`Accuracy: ${PCT(d.routing_accuracy)}`, `${d.correct ?? '—'} / ${d.total ?? '—'} correct`)
  } else if (dimKey === 'entity_extraction') {
    details.push(
      `Policy P/R/F1: ${PCT(d.policy_number?.precision)} / ${PCT(d.policy_number?.recall)} / ${PCT(d.policy_number?.f1)}`,
      `PII Flag F1: ${PCT(d.pii_flag?.f1)}`
    )
  } else if (dimKey === 'rag_retrieval') {
    details.push(`Hit Rate: ${PCT(d.hit_rate)}`, `Avg Docs: ${d.avg_docs_retrieved ?? FMT(d.mrr)}`)
  } else if (dimKey === 'response_quality') {
    details.push(
      `Hedge Rate: ${PCT(d.hedge_rate)}`,
      `Escalation Agreement: ${d.escalation_agreement != null ? PCT(d.escalation_agreement) : 'N/A'}`
    )
  } else if (dimKey === 'confidence_calibration') {
    details.push(
      `ECE: ${FMT(d.ece)}`,
      `Auto Response: ${PCT(d.routing_distribution?.auto_response)}`,
      `Human Review: ${PCT(d.routing_distribution?.human_review)}`,
      `Escalate: ${PCT(d.routing_distribution?.escalate)}`
    )
  }

  return (
    <div className="card" style={{ padding: '1.25rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
        <h4 style={{ margin: 0, fontSize: '0.95rem', color: '#2c3e50' }}>{label}</h4>
        <span style={{ fontWeight: 700, fontSize: '1.4rem', color }}>{pct.toFixed(1)}%</span>
      </div>
      <div style={{ background: '#f0f0f0', borderRadius: '4px', height: '6px', marginBottom: '0.75rem' }}>
        <div style={{ width: `${Math.min(pct, 100)}%`, height: '6px', borderRadius: '4px', background: color }} />
      </div>
      {details.map((line, i) => (
        <div key={i} style={{ fontSize: '0.78rem', color: '#555', lineHeight: 1.6 }}>{line}</div>
      ))}
    </div>
  )
}

function Assessment({ apiUrl }) {
  const [data,      setData]      = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [runStatus, setRunStatus] = useState(null)
  const [running,   setRunning]   = useState(false)

  useEffect(() => { fetchData() }, [])

  const fetchData = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await axios.get(`${apiUrl}/api/assessment`)
      setData(res.data)
    } catch (err) {
      setError(err.response?.status === 404 ? 'No assessment report found. Run the pipeline first.' : err.message)
    } finally {
      setLoading(false)
    }
  }

  const triggerRun = async () => {
    try {
      setRunning(true)
      setRunStatus(null)
      const res = await axios.post(`${apiUrl}/api/assessment/run`)
      setRunStatus(res.data)
    } catch (err) {
      setRunStatus({ error: err.message })
    } finally {
      setRunning(false)
    }
  }

  const meta       = data?.assessment_metadata || {}
  const dims       = data?.dimensions || {}
  const composite  = data?.composite_score ?? 0
  const passed     = meta.passed
  const findings   = data?.code_quality_assessment?.findings || []
  const sevSummary = data?.code_quality_assessment?.severity_summary || {}

  const radarData = Object.keys(DIMENSION_LABELS).map(key => ({
    subject: DIMENSION_LABELS[key],
    score:   +scoreToPct(key, dims).toFixed(1),
  }))

  const calibDist  = dims.confidence_calibration?.routing_distribution || {}
  const routingData = Object.entries(calibDist).map(([name, val]) => ({
    name: name.replace('_', ' '),
    value: +(val * 100).toFixed(1),
  }))

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <h2 style={{ margin: 0, fontSize: '1.75rem' }}>E2E Pipeline Assessment</h2>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            onClick={fetchData}
            disabled={loading}
            style={{
              padding: '0.5rem 1.25rem', borderRadius: '6px', border: '1px solid #667eea',
              background: 'white', color: '#667eea', cursor: 'pointer', fontWeight: 500,
            }}
          >
            {loading ? 'Loading…' : 'Refresh'}
          </button>
          <button
            onClick={triggerRun}
            disabled={running}
            style={{
              padding: '0.5rem 1.25rem', borderRadius: '6px', border: 'none',
              background: '#667eea', color: 'white', cursor: 'pointer', fontWeight: 600,
            }}
          >
            {running ? 'Running…' : 'Run Live Pipeline'}
          </button>
        </div>
      </div>

      {runStatus && (
        <div style={{
          marginBottom: '1rem', padding: '0.75rem 1rem', borderRadius: '6px',
          background: runStatus.error ? '#f8d7da' : '#d4edda',
          color: runStatus.error ? '#721c24' : '#155724',
          fontSize: '0.875rem',
        }}>
          {runStatus.error ? `Error: ${runStatus.error}` : runStatus.message || JSON.stringify(runStatus)}
        </div>
      )}

      {error && !data && (
        <div className="card" style={{ color: '#721c24', background: '#f8d7da' }}>
          {error}
          <div style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
            Run: <code>python scripts/run_stepfn_assessment.py --sample 20</code>
          </div>
        </div>
      )}

      {data && (
        <>
          {/* ── Composite Score Header ───────────────────────────────── */}
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '2rem', flexWrap: 'wrap' }}>
              <div style={{
                padding: '1rem 2rem', borderRadius: '10px',
                background: passed ? '#d4edda' : '#f8d7da',
                color: passed ? '#155724' : '#721c24',
                textAlign: 'center',
              }}>
                <div style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Composite Score
                </div>
                <div style={{ fontSize: '2.5rem', fontWeight: 800, lineHeight: 1.1 }}>
                  {(composite * 100).toFixed(1)}%
                </div>
                <div style={{ fontSize: '1rem', fontWeight: 700 }}>
                  {passed ? '✓ PASSED' : '✗ FAILED'}
                </div>
              </div>

              <div>
                <span style={{
                  display: 'inline-block', padding: '0.3rem 0.8rem', borderRadius: '6px',
                  fontWeight: 700, fontSize: '0.8rem', marginBottom: '0.75rem',
                  background: '#cce5ff', color: '#004085',
                }}>
                  LIVE — Step Function Pipeline
                </span>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem 2rem', fontSize: '0.875rem', color: '#555' }}>
                  <span><strong>Emails:</strong> {meta.n_emails ?? '—'}</span>
                  <span><strong>Succeeded:</strong> {meta.n_succeeded ?? '—'} / {meta.n_emails ?? '—'}</span>
                  <span><strong>Elapsed:</strong> {meta.elapsed_seconds != null ? `${meta.elapsed_seconds.toFixed(1)}s` : '—'}</span>
                  <span><strong>Threshold:</strong> {PCT(meta.pass_threshold)}</span>
                  {meta.run_id && <span style={{ gridColumn: 'span 2' }}><strong>Run ID:</strong> <code>{meta.run_id}</code></span>}
                  <span style={{ gridColumn: 'span 2' }}>
                    <strong>Generated:</strong> {meta.generated_at ? new Date(meta.generated_at).toLocaleString() : '—'}
                  </span>
                </div>
              </div>

              {Object.keys(sevSummary).length > 0 && (
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  {Object.entries(sevSummary).map(([sev, count]) => count > 0 && (
                    <span key={sev} style={{
                      padding: '0.2rem 0.6rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                      ...SEVERITY_STYLE[sev],
                    }}>
                      {count} {sev}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ── Dimension Score Cards ────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
            {Object.keys(DIMENSION_LABELS).map(k => (
              <DimensionCard key={k} dimKey={k} dims={dims} />
            ))}
          </div>

          {/* ── Radar + Routing Distribution ─────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1.5rem' }}>
            <div className="card">
              <h3 className="card-title">Pipeline Radar</h3>
              <ResponsiveContainer width="100%" height={300}>
                <RadarChart data={radarData}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11 }} />
                  <PolarRadiusAxis angle={90} domain={[0, 100]} tickFormatter={v => `${v}%`} tick={{ fontSize: 10 }} />
                  <Radar name="Score" dataKey="score" stroke="#667eea" fill="#667eea" fillOpacity={0.35} />
                  <Tooltip formatter={v => `${v}%`} />
                </RadarChart>
              </ResponsiveContainer>
            </div>

            <div className="card">
              <h3 className="card-title">Routing Distribution</h3>
              {routingData.length > 0 ? (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={routingData} barCategoryGap="35%">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} />
                    <Tooltip formatter={v => `${v}%`} />
                    <Bar dataKey="value" fill="#667eea" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p style={{ color: '#7f8c8d' }}>No calibration data.</p>
              )}
              {dims.confidence_calibration && (
                <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: '#555' }}>
                  ECE: <strong>{FMT(dims.confidence_calibration.ece)}</strong>
                </div>
              )}
            </div>
          </div>

          {/* ── Per-Email Results ────────────────────────────────────── */}
          {data.per_email_results?.length > 0 && (
            <div className="card">
              <h3 className="card-title">
                Per-Email Results ({Math.min(data.per_email_results.length, 50)} of {meta.n_succeeded})
              </h3>
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Email ID</th>
                      <th>Gold Intent</th>
                      <th>Predicted</th>
                      <th>Match</th>
                      <th>Gold Route</th>
                      <th>Predicted Route</th>
                      <th>Confidence</th>
                      <th>Action</th>
                      <th>RAG Docs</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.per_email_results.slice(0, 50).map(r => {
                      const intentMatch = r.predicted_intent === r.gold_intent
                      const routeMatch  = r.predicted_route?.toLowerCase() === r.gold_route_team?.toLowerCase()
                      const actionColor = r.action === 'auto_response' ? '#28a745'
                                        : r.action === 'human_review'  ? '#f39c12' : '#dc3545'
                      return (
                        <tr key={r.laya_email_id}>
                          <td style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                            {r.laya_email_id?.slice(0, 12)}…
                          </td>
                          <td style={{ fontSize: '0.8rem' }}>{r.gold_intent}</td>
                          <td style={{ fontSize: '0.8rem', color: intentMatch ? '#28a745' : '#dc3545', fontWeight: intentMatch ? 400 : 600 }}>
                            {r.predicted_intent}
                          </td>
                          <td style={{ textAlign: 'center' }}>{intentMatch ? '✓' : '✗'}</td>
                          <td style={{ fontSize: '0.75rem' }}>{r.gold_route_team}</td>
                          <td style={{ fontSize: '0.75rem', color: routeMatch ? '#28a745' : '#dc3545' }}>
                            {r.predicted_route}
                          </td>
                          <td>{r.confidence_score != null ? r.confidence_score.toFixed(3) : '—'}</td>
                          <td>
                            <span style={{
                              padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.72rem', fontWeight: 600,
                              background: actionColor + '22', color: actionColor,
                            }}>
                              {r.action}
                            </span>
                          </td>
                          <td style={{ textAlign: 'center' }}>{r.rag_hit_count ?? 0}</td>
                          <td>
                            <span style={{
                              padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.72rem',
                              background: r.exec_status === 'SUCCEEDED' ? '#d4edda' : '#f8d7da',
                              color: r.exec_status === 'SUCCEEDED' ? '#155724' : '#721c24',
                            }}>
                              {r.exec_status}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Top Confused Intents ─────────────────────────────────── */}
          {dims.intent_classification?.top_confused?.length > 0 && (
            <div className="card">
              <h3 className="card-title">Top Confused Intent Pairs</h3>
              <div className="table-container">
                <table>
                  <thead>
                    <tr><th>True Intent</th><th>Predicted As</th><th>Count</th></tr>
                  </thead>
                  <tbody>
                    {dims.intent_classification.top_confused.map((row, i) => (
                      <tr key={i}>
                        <td>{row.true}</td>
                        <td style={{ color: '#dc3545' }}>{row.predicted}</td>
                        <td><strong>{row.count}</strong></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default Assessment
