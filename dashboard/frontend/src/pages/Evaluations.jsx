import React, { useState, useEffect } from 'react'
import axios from 'axios'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis
} from 'recharts'

const MODEL_COLORS = {
  'mistral-7b': '#667eea',
  'llama-3-8b': '#f093fb',
  'claude-haiku': '#4facfe',
}

const SCORE_PERCENT = v => `${(v * 100).toFixed(1)}%`
const PCT = v => v != null ? `${(v * 100).toFixed(1)}%` : '—'

function RefEvalSection({ refEval }) {
  if (!refEval || !refEval.aggregate) return (
    <div className="card">
      <h3 className="card-title">Reference Evaluation (RAG Pipeline)</h3>
      <p style={{ color: '#7f8c8d' }}>No reference eval report available. Run <code>scripts/reference_eval.py</code> to generate one.</p>
    </div>
  )

  const agg = refEval.aggregate
  const results = refEval.results || []
  const composite = agg.composite_score || 0
  const passed = composite >= 0.75

  const aggData = [
    { metric: 'Key Fact Recall',     value: +(agg.avg_key_fact_recall * 100).toFixed(1) },
    { metric: 'Hallucination Rate',  value: +(agg.hallucination_rate  * 100).toFixed(1) },
    { metric: 'Out-of-Scope Refusal',value: +(agg.out_of_scope_refusal_rate * 100).toFixed(1) },
    { metric: 'Response Length OK',  value: +(agg.response_length_ok_rate  * 100).toFixed(1) },
    { metric: 'Hedge Rate',          value: +(agg.hedge_rate * 100).toFixed(1) },
  ]

  return (
    <div className="card">
      <h3 className="card-title">Reference Evaluation (RAG Pipeline)</h3>
      <p style={{ color: '#7f8c8d', fontSize: '0.875rem', marginBottom: '1rem' }}>
        Deterministic reference-free eval: key fact recall, hallucination detection, out-of-scope refusal
      </p>

      {/* Composite score badge */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
        <div style={{
          padding: '0.75rem 1.5rem',
          borderRadius: '8px',
          background: passed ? '#d4edda' : '#f8d7da',
          color: passed ? '#155724' : '#721c24',
          fontWeight: 700, fontSize: '1.25rem',
        }}>
          Composite Score: {PCT(composite)} {passed ? '✓ PASS' : '✗ FAIL'}
        </div>
        <span style={{ color: '#7f8c8d', fontSize: '0.875rem' }}>
          Threshold: 75% &nbsp;|&nbsp; {agg.total} queries evaluated
        </span>
      </div>

      {/* Bar chart of aggregate metrics */}
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={aggData} barCategoryGap="30%">
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="metric" tick={{ fontSize: 12 }} />
          <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} />
          <Tooltip formatter={v => `${v}%`} />
          <Bar dataKey="value" fill="#667eea" />
        </BarChart>
      </ResponsiveContainer>

      {/* Per-query table */}
      <div className="table-container" style={{ marginTop: '1.5rem' }}>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Query</th>
              <th>Recall</th>
              <th>Hallucinated</th>
              <th>OOS Refused</th>
              <th>Docs</th>
              <th>Composite</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {results.map(r => {
              const pass = r.composite >= 0.75
              return (
                <tr key={r.query_id}>
                  <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{r.query_id}</td>
                  <td style={{ maxWidth: '240px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {r.query}
                  </td>
                  <td>{PCT(r.key_fact_recall)}</td>
                  <td>
                    <span style={{
                      padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.75rem',
                      background: r.hallucination_flag ? '#f8d7da' : '#d4edda',
                      color: r.hallucination_flag ? '#721c24' : '#155724',
                    }}>
                      {r.hallucination_flag ? 'Yes' : 'No'}
                    </span>
                  </td>
                  <td>
                    <span style={{
                      padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.75rem',
                      background: r.out_of_scope_refused ? '#d4edda' : '#fff3cd',
                      color: r.out_of_scope_refused ? '#155724' : '#856404',
                    }}>
                      {r.out_of_scope_refused ? 'Yes' : 'No'}
                    </span>
                  </td>
                  <td>{r.retrieved_docs}</td>
                  <td><strong>{PCT(r.composite)}</strong></td>
                  <td>
                    <span style={{
                      padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                      background: pass ? '#d4edda' : '#f8d7da',
                      color: pass ? '#155724' : '#721c24',
                    }}>
                      {pass ? 'PASS' : 'FAIL'}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Evaluations({ apiUrl }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [bedrockTab, setBedrockTab] = useState('model_evaluation')

  useEffect(() => { fetchData() }, [])

  const fetchData = async () => {
    try {
      setLoading(true)
      const res = await axios.get(`${apiUrl}/api/metrics/evaluations`)
      setData(res.data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading evaluation metrics...</div>
  if (error) return <div className="error">Error: {error}</div>
  if (!data) return <div className="loading">No data available</div>

  const { reference_eval = {}, bedrock_evals = [], claude_evals = [] } = data

  // --- Bedrock chart data ---
  const bedrockFiltered = bedrock_evals.filter(e => e.eval_type === bedrockTab && e.eval_status === 'Completed')
  const bedrockChartData = bedrockFiltered.map(e => ({
    name: e.model_name,
    Correctness:  +(e.score_correctness  * 100).toFixed(1),
    Completeness: +(e.score_completeness * 100).toFixed(1),
    Helpfulness:  +(e.score_helpfulness  * 100).toFixed(1),
    Faithfulness: +(e.score_faithfulness * 100).toFixed(1),
  }))

  const bedrockMetrics = bedrockTab === 'rag_evaluation'
    ? ['Faithfulness', 'Correctness', 'Completeness']
    : ['Correctness', 'Completeness', 'Helpfulness']

  const bedrockBarColors = ['#667eea', '#28a745', '#f39c12', '#e74c3c']

  // --- Claude-as-judge chart data ---
  const claudeChartData = claude_evals.map(e => ({
    name: e.model_name,
    Accuracy:      +((e.avg_scores?.accuracy      || 0) * 100).toFixed(1),
    'Task Accuracy': +((e.avg_scores?.task_accuracy || 0) * 100).toFixed(1),
    Compliance:    +((e.avg_scores?.compliance    || 0) * 100).toFixed(1),
    Coherence:     +((e.avg_scores?.coherence     || 0) * 100).toFixed(1),
    Overall:       +((e.avg_scores?.overall       || 0) * 100).toFixed(1),
  }))

  // Radar data (one entry per metric, values per model)
  const radarMetrics = ['Accuracy', 'Task Accuracy', 'Compliance', 'Coherence', 'Overall']
  const radarData = radarMetrics.map(metric => {
    const entry = { metric }
    claudeChartData.forEach(m => { entry[m.name] = m[metric] })
    return entry
  })

  // Per-task breakdown (union of all task types)
  const allTasks = [...new Set(claude_evals.flatMap(e => Object.keys(e.by_task || {})))]

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.75rem' }}>Model Evaluation Results</h2>

      {/* ── Reference Eval ────────────────────────────────────────── */}
      <RefEvalSection refEval={reference_eval} />

      {/* ── AWS Bedrock Automated Evaluation ─────────────────────── */}
      <div className="card">
        <h3 className="card-title">AWS Bedrock Automated Evaluation</h3>
        <p style={{ color: '#7f8c8d', fontSize: '0.875rem', marginBottom: '1rem' }}>
          LLM-as-judge (Claude Haiku) scores on {bedrock_evals.length} evaluation jobs
        </p>

        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
          {['model_evaluation', 'rag_evaluation'].map(tab => (
            <button
              key={tab}
              onClick={() => setBedrockTab(tab)}
              style={{
                padding: '0.4rem 1rem',
                borderRadius: '6px',
                border: '1px solid #667eea',
                cursor: 'pointer',
                background: bedrockTab === tab ? '#667eea' : 'white',
                color: bedrockTab === tab ? 'white' : '#667eea',
                fontWeight: bedrockTab === tab ? 600 : 400,
              }}
            >
              {tab === 'model_evaluation' ? 'Model QA' : 'RAG Faithfulness'}
            </button>
          ))}
        </div>

        {bedrockChartData.length === 0 ? (
          <p style={{ color: '#7f8c8d' }}>No completed evaluations for this type yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={bedrockChartData} barCategoryGap="30%">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} />
              <Tooltip formatter={v => `${v}%`} />
              <Legend />
              {bedrockMetrics.map((m, i) => (
                <Bar key={m} dataKey={m} fill={bedrockBarColors[i]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}

        <div className="table-container" style={{ marginTop: '1.5rem' }}>
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Eval Type</th>
                <th>Correctness</th>
                <th>Completeness</th>
                <th>Helpfulness</th>
                <th>Faithfulness</th>
                <th>Status</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {bedrock_evals.map((e, i) => (
                <tr key={i}>
                  <td><strong>{e.model_name}</strong></td>
                  <td>{e.eval_type === 'model_evaluation' ? 'Model QA' : 'RAG'}</td>
                  <td>{e.score_correctness  != null ? SCORE_PERCENT(e.score_correctness)  : '—'}</td>
                  <td>{e.score_completeness != null ? SCORE_PERCENT(e.score_completeness) : '—'}</td>
                  <td>{e.score_helpfulness  != null ? SCORE_PERCENT(e.score_helpfulness)  : '—'}</td>
                  <td>{e.score_faithfulness != null ? SCORE_PERCENT(e.score_faithfulness) : '—'}</td>
                  <td>
                    <span style={{
                      padding: '0.2rem 0.5rem',
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                      background: e.eval_status === 'Completed' ? '#d4edda' : '#fff3cd',
                      color: e.eval_status === 'Completed' ? '#155724' : '#856404',
                    }}>
                      {e.eval_status}
                    </span>
                  </td>
                  <td style={{ fontSize: '0.75rem', color: '#7f8c8d' }}>
                    {e.timestamp ? new Date(e.timestamp).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Claude-as-Judge (LLM Response Evaluation) ──────────────── */}
      <div className="card">
        <h3 className="card-title">Claude-as-Judge: Live Response Scores</h3>
        <p style={{ color: '#7f8c8d', fontSize: '0.875rem', marginBottom: '1rem' }}>
          Per-response evaluation scored by Claude Haiku after each production inference
        </p>

        {claudeChartData.length === 0 ? (
          <p style={{ color: '#7f8c8d' }}>No Claude-as-judge scores recorded yet.</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
            <div>
              <h4 style={{ marginBottom: '0.75rem', color: '#2c3e50' }}>Score Comparison</h4>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={claudeChartData} barCategoryGap="25%">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} />
                  <Tooltip formatter={v => `${v}%`} />
                  <Legend />
                  <Bar dataKey="Accuracy"       fill="#667eea" />
                  <Bar dataKey="Task Accuracy"  fill="#f093fb" />
                  <Bar dataKey="Compliance"     fill="#4facfe" />
                  <Bar dataKey="Coherence"      fill="#43e97b" />
                  <Bar dataKey="Overall"        fill="#f39c12" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div>
              <h4 style={{ marginBottom: '0.75rem', color: '#2c3e50' }}>Radar View</h4>
              <ResponsiveContainer width="100%" height={300}>
                <RadarChart data={radarData}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="metric" />
                  <PolarRadiusAxis angle={90} domain={[0, 100]} tickFormatter={v => `${v}%`} />
                  {claude_evals.map(e => (
                    <Radar
                      key={e.model_name}
                      name={e.model_name}
                      dataKey={e.model_name}
                      stroke={MODEL_COLORS[e.model_name] || '#888'}
                      fill={MODEL_COLORS[e.model_name] || '#888'}
                      fillOpacity={0.25}
                    />
                  ))}
                  <Legend />
                  <Tooltip formatter={v => `${v}%`} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {claude_evals.length > 0 && (
          <div className="table-container" style={{ marginTop: '1.5rem' }}>
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Samples</th>
                  <th>Accuracy</th>
                  <th>Task Accuracy</th>
                  <th>Compliance</th>
                  <th>Coherence</th>
                  <th>Overall</th>
                </tr>
              </thead>
              <tbody>
                {claude_evals.map(e => (
                  <tr key={e.model_name}>
                    <td><strong>{e.model_name}</strong></td>
                    <td>{e.sample_count ?? '—'}</td>
                    <td>{SCORE_PERCENT(e.avg_scores?.accuracy      || 0)}</td>
                    <td>{SCORE_PERCENT(e.avg_scores?.task_accuracy  || 0)}</td>
                    <td>{SCORE_PERCENT(e.avg_scores?.compliance     || 0)}</td>
                    <td>{SCORE_PERCENT(e.avg_scores?.coherence      || 0)}</td>
                    <td>
                      <strong style={{ color: (e.avg_scores?.overall || 0) >= 0.8 ? '#28a745' : '#f39c12' }}>
                        {SCORE_PERCENT(e.avg_scores?.overall || 0)}
                      </strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Per-Task Breakdown ───────────────────────────────────── */}
      {allTasks.length > 0 && (
        <div className="card">
          <h3 className="card-title">Claude-as-Judge: Per Task Type</h3>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Task Type</th>
                  {claude_evals.map(e => (
                    <th key={e.model_name} colSpan={2} style={{ textAlign: 'center', borderLeft: '2px solid #dee2e6' }}>
                      {e.model_name}
                    </th>
                  ))}
                </tr>
                <tr>
                  <th></th>
                  {claude_evals.map(e => (
                    <React.Fragment key={e.model_name}>
                      <th style={{ borderLeft: '2px solid #dee2e6', fontWeight: 400, fontSize: '0.8rem' }}>Overall</th>
                      <th style={{ fontWeight: 400, fontSize: '0.8rem' }}>Task Acc.</th>
                    </React.Fragment>
                  ))}
                </tr>
              </thead>
              <tbody>
                {allTasks.map(task => (
                  <tr key={task}>
                    <td><strong>{task}</strong></td>
                    {claude_evals.map(e => {
                      const ts = e.by_task?.[task]
                      return (
                        <React.Fragment key={e.model_name}>
                          <td style={{ borderLeft: '2px solid #dee2e6' }}>
                            {ts ? SCORE_PERCENT(ts.overall || 0) : '—'}
                          </td>
                          <td>{ts ? SCORE_PERCENT(ts.task_accuracy || 0) : '—'}</td>
                        </React.Fragment>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

export default Evaluations
