import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import Assessment from './Assessment'

const PCT = v => v != null ? `${(v * 100).toFixed(1)}%` : '—'

const TAB_STYLE = (active) => ({
  padding: '0.5rem 1.25rem',
  borderRadius: '6px',
  border: `1px solid ${active ? '#667eea' : '#dee2e6'}`,
  cursor: 'pointer',
  background: active ? '#667eea' : 'white',
  color: active ? 'white' : '#495057',
  fontWeight: active ? 600 : 400,
  fontSize: '0.9rem',
})

function Evaluations({ apiUrl }) {
  const [tab,     setTab]     = useState('reference')
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <h2 style={{ margin: 0, fontSize: '1.75rem' }}>Evaluation Results</h2>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button style={TAB_STYLE(tab === 'reference')} onClick={() => setTab('reference')}>
            Reference Evaluation
          </button>
          <button style={TAB_STYLE(tab === 'assessment')} onClick={() => setTab('assessment')}>
            Pipeline Assessment
          </button>
        </div>
      </div>

      {tab === 'assessment' && <Assessment apiUrl={apiUrl} />}
      {tab === 'reference'  && <ReferenceEval apiUrl={apiUrl} data={data} loading={loading} error={error} />}
    </div>
  )
}

function ReferenceEval({ data, loading, error }) {
  if (loading) return <div className="loading">Loading evaluation metrics...</div>
  if (error)   return <div className="error">Error: {error}</div>

  const refEval = data?.reference_eval || {}

  if (!refEval.aggregate) return (
    <div className="card">
      <h3 className="card-title">Reference Evaluation (RAG Pipeline)</h3>
      <p style={{ color: '#7f8c8d' }}>
        No reference eval report available. Run <code>scripts/reference_eval.py</code> to generate one.
      </p>
    </div>
  )

  const agg     = refEval.aggregate
  const results = refEval.results || []
  const composite = agg.composite_score || 0
  const passed  = composite >= 0.75

  const aggData = [
    { metric: 'Key Fact Recall',      value: +(agg.avg_key_fact_recall       * 100).toFixed(1) },
    { metric: 'Hallucination Rate',   value: +(agg.hallucination_rate        * 100).toFixed(1) },
    { metric: 'Out-of-Scope Refusal', value: +(agg.out_of_scope_refusal_rate * 100).toFixed(1) },
    { metric: 'Response Length OK',   value: +(agg.response_length_ok_rate   * 100).toFixed(1) },
    { metric: 'Hedge Rate',           value: +(agg.hedge_rate                * 100).toFixed(1) },
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
            padding: '0.75rem 1.5rem', borderRadius: '8px',
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

        {/* Bar chart */}
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
                        color:      r.hallucination_flag ? '#721c24' : '#155724',
                      }}>
                        {r.hallucination_flag ? 'Yes' : 'No'}
                      </span>
                    </td>
                    <td>
                      <span style={{
                        padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.75rem',
                        background: r.out_of_scope_refused ? '#d4edda' : '#fff3cd',
                        color:      r.out_of_scope_refused ? '#155724' : '#856404',
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
                        color:      pass ? '#155724' : '#721c24',
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

export default Evaluations
