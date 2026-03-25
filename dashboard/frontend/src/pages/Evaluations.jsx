import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import Assessment from './Assessment'

const PCT = v => v != null ? `${(v * 100).toFixed(1)}%` : '—'
const FMT4 = v => v != null ? v.toFixed(4) : '—'

const TAB_STYLE = (active) => ({
  padding: '0.5rem 1.1rem',
  borderRadius: '6px',
  border: `1px solid ${active ? '#667eea' : '#dee2e6'}`,
  cursor: 'pointer',
  background: active ? '#667eea' : 'white',
  color: active ? 'white' : '#495057',
  fontWeight: active ? 600 : 400,
  fontSize: '0.85rem',
  whiteSpace: 'nowrap',
})

const BADGE = (pass) => ({
  display: 'inline-block',
  padding: '0.35rem 0.9rem',
  borderRadius: '6px',
  fontWeight: 700,
  fontSize: '1rem',
  background: pass ? '#d4edda' : '#f8d7da',
  color: pass ? '#155724' : '#721c24',
})

const CARD = {
  background: '#f8f9fa',
  borderRadius: '8px',
  padding: '1rem 1.25rem',
  textAlign: 'center',
  minWidth: '120px',
}

function StatCard({ label, value, sub }) {
  return (
    <div style={CARD}>
      <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: '0.8rem', color: '#6c757d', marginTop: '0.2rem' }}>{label}</div>
      {sub && <div style={{ fontSize: '0.75rem', color: '#adb5bd' }}>{sub}</div>}
    </div>
  )
}

function LoadState({ loading, error, children }) {
  if (loading) return <div className="loading">Loading...</div>
  if (error)   return <div className="error">Error: {error}</div>
  return children
}

// Lazy fetch hook — fetches only when tab first becomes active
function useLazyFetch(url, tab, activeTab) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)
  const fetched = useRef(false)

  useEffect(() => {
    if (activeTab === tab && !fetched.current) {
      fetched.current = true
      setLoading(true)
      axios.get(url)
        .then(r => setData(r.data))
        .catch(e => setError(e.response?.data?.error || e.message))
        .finally(() => setLoading(false))
    }
  }, [activeTab, tab, url])

  return { data, loading, error }
}

const TABS = [
  { key: 'pipeline',  label: 'E2E Pipeline'       },
  { key: 'intent',    label: 'Intent & Routing'    },
  { key: 'claim',     label: 'Attachment Parsing'  },
  { key: 'rag',       label: 'RAG Retrieval'       },
  { key: 'response',  label: 'Response Generation' },
  { key: 'reference', label: 'Reference Eval'      },
]

function Evaluations({ apiUrl }) {
  const [tab, setTab] = useState('pipeline')

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <h2 style={{ margin: 0, fontSize: '1.75rem' }}>Evaluation Results</h2>
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button key={t.key} style={TAB_STYLE(tab === t.key)} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'pipeline'  && <Assessment apiUrl={apiUrl} />}
      {tab === 'intent'    && <IntentEval   apiUrl={apiUrl} activeTab={tab} />}
      {tab === 'claim'     && <ClaimEval    apiUrl={apiUrl} activeTab={tab} />}
      {tab === 'rag'       && <RagEval      apiUrl={apiUrl} activeTab={tab} />}
      {tab === 'response'  && <ResponseEval apiUrl={apiUrl} activeTab={tab} />}
      {tab === 'reference' && <ReferenceEval apiUrl={apiUrl} activeTab={tab} />}
    </div>
  )
}

// ── Intent & Routing ──────────────────────────────────────────────────────────

function IntentEval({ apiUrl, activeTab }) {
  const { data, loading, error } = useLazyFetch(`${apiUrl}/api/metrics/intent-eval`, 'intent', activeTab)

  return (
    <LoadState loading={loading} error={error}>
      {data ? <IntentEvalContent data={data} /> : <NoData script="run_intent_eval.py" />}
    </LoadState>
  )
}

function IntentEvalContent({ data }) {
  const rs = data.run_summary || {}
  const ic = data.intent_classification || {}
  const ro = data.routing || {}
  const passed = (ic.accuracy || 0) >= 0.80

  const perClassData = Object.entries(ic.per_class || {})
    .map(([intent, s]) => ({ intent: intent.replace(/_/g, ' '), f1: +(s.f1 * 100).toFixed(1) }))
    .sort((a, b) => b.f1 - a.f1)

  return (
    <div className="card">
      <h3 className="card-title">Intent Classification Evaluation</h3>

      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem', alignItems: 'center' }}>
        <div style={BADGE(passed)}>
          Accuracy: {PCT(ic.accuracy)} {passed ? '✓ PASS' : '✗ FAIL'}
        </div>
        <span style={{ color: '#7f8c8d', fontSize: '0.875rem' }}>threshold: 80%</span>
        <StatCard label="Macro F1"  value={FMT4(ic.macro_f1)} />
        <StatCard label="Emails"    value={rs.n_emails || '—'} />
        <StatCard label="Succeeded" value={rs.n_succeeded || '—'} />
        <StatCard label="Avg Latency" value={rs.avg_latency_ms ? `${rs.avg_latency_ms}ms` : '—'} />
        <StatCard label="Routing Acc" value={PCT(ro.routing_accuracy)} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        <div>
          <h4 style={{ marginBottom: '0.75rem' }}>Per-Class F1 (top intents)</h4>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={perClassData.slice(0, 12)} layout="vertical" margin={{ left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} />
              <YAxis type="category" dataKey="intent" width={150} tick={{ fontSize: 10 }} />
              <Tooltip formatter={v => `${v}%`} />
              <Bar dataKey="f1" fill="#667eea" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div>
          <h4 style={{ marginBottom: '0.75rem' }}>Per-Class Detail</h4>
          <div className="table-container" style={{ maxHeight: '280px', overflowY: 'auto' }}>
            <table>
              <thead>
                <tr><th>Intent</th><th>Sup</th><th>Prec</th><th>Rec</th><th>F1</th></tr>
              </thead>
              <tbody>
                {Object.entries(ic.per_class || {}).sort((a,b) => b[1].support - a[1].support).map(([intent, s]) => (
                  <tr key={intent}>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{intent}</td>
                    <td>{s.support}</td>
                    <td>{PCT(s.precision)}</td>
                    <td>{PCT(s.recall)}</td>
                    <td><F1Badge v={s.f1} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {(ic.top_confused || []).length > 0 && (
            <>
              <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Top Confused Pairs</h4>
              <table>
                <thead><tr><th>True</th><th>Predicted</th><th>N</th></tr></thead>
                <tbody>
                  {ic.top_confused.map((p, i) => (
                    <tr key={i}>
                      <td style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{p.true}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{p.predicted}</td>
                      <td>{p.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Claim / Attachment Parsing ────────────────────────────────────────────────

function ClaimEval({ apiUrl, activeTab }) {
  const { data, loading, error } = useLazyFetch(`${apiUrl}/api/metrics/claim-extraction`, 'claim', activeTab)

  return (
    <LoadState loading={loading} error={error}>
      {data ? <ClaimEvalContent data={data} /> : <NoData script="run_claim_extraction_eval.py" />}
    </LoadState>
  )
}

function ClaimEvalContent({ data }) {
  // JSON uses total_records/successful/failed (not n_records/n_succeeded)
  const rs   = data.run_summary || {}
  const os   = data.overall_score ?? null
  const passed = (os || 0) >= 0.80
  const sf   = data.field_results         || {}   // string fields
  const nf   = data.numeric_field_results || {}
  const rec  = data.receipts_results      || {}
  const dep  = data.dependants_results    || {}

  return (
    <div className="card">
      <h3 className="card-title">Attachment Parsing Evaluation</h3>

      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem', alignItems: 'center' }}>
        <div style={BADGE(passed)}>
          Score: {os != null ? os.toFixed(4) : '—'} {passed ? '✓ PASS' : '✗ FAIL'}
        </div>
        <span style={{ color: '#7f8c8d', fontSize: '0.875rem' }}>threshold: 0.80</span>
        <StatCard label="Records"    value={rs.total_records ?? '—'} />
        <StatCard label="Succeeded"  value={rs.successful    ?? '—'} />
        <StatCard label="Avg Confidence" value={rs.avg_confidence != null ? rs.avg_confidence.toFixed(3) : '—'} />
        <StatCard label="Avg Latency"    value={rs.avg_latency_ms ? `${Math.round(rs.avg_latency_ms)}ms` : '—'} />
      </div>

      {/* String fields */}
      {Object.keys(sf).length > 0 && (
        <>
          <h4 style={{ marginBottom: '0.5rem' }}>String Fields</h4>
          <div className="table-container" style={{ marginBottom: '1.25rem' }}>
            <table>
              <thead>
                <tr><th>Field</th><th>GP</th><th>Prec(E)</th><th>Rec(E)</th><th>F1(E)</th><th>F1(P)</th><th>Null Acc</th></tr>
              </thead>
              <tbody>
                {Object.entries(sf).filter(([,s]) => (s.gold_present || 0) > 0).sort((a,b) => (b[1].gold_present||0) - (a[1].gold_present||0)).map(([fname, s]) => (
                  <tr key={fname}>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{fname}</td>
                    <td>{s.gold_present}</td>
                    <td>{PCT(s.precision_exact)}</td>
                    <td>{PCT(s.recall_exact)}</td>
                    <td><F1Badge v={s.f1_exact} /></td>
                    <td><F1Badge v={s.f1_partial} /></td>
                    <td>{s.null_accuracy != null ? PCT(s.null_accuracy) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Mini cards for other field types */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
        {Object.keys(nf).length > 0 && (
          <MiniCard title="Numeric Fields" items={Object.entries(nf).map(([k,v]) => ({ label: k, value: v?.mae != null ? `MAE ${v.mae.toFixed(2)}` : '—' }))} />
        )}
        {(rec.treatment_type_f1 != null || rec.cost_within_5pct_accuracy != null) && (
          <MiniCard title="Receipts" items={[
            { label: 'Treatment F1', value: rec.treatment_type_f1 != null ? rec.treatment_type_f1.toFixed(4) : '—' },
            { label: 'Cost ±5%', value: PCT(rec.cost_within_5pct_accuracy) },
            { label: 'Total rows', value: rec.total_gold_rows ?? '—' },
          ]} />
        )}
        {(dep.detection_recall != null || dep.name_match_f1 != null) && (
          <MiniCard title="Dependants" items={[
            { label: 'Det. Recall', value: PCT(dep.detection_recall) },
            { label: 'Name F1', value: dep.name_match_f1 != null ? dep.name_match_f1.toFixed(4) : '—' },
            { label: 'Records', value: dep.records_with_dependants ?? '—' },
          ]} />
        )}
      </div>
    </div>
  )
}

// ── RAG Retrieval ─────────────────────────────────────────────────────────────

function RagEval({ apiUrl, activeTab }) {
  const { data, loading, error } = useLazyFetch(`${apiUrl}/api/metrics/rag-eval`, 'rag', activeTab)

  return (
    <LoadState loading={loading} error={error}>
      {data ? <RagEvalContent data={data} /> : <NoData script="run_rag_eval.py" />}
    </LoadState>
  )
}

function RagEvalContent({ data }) {
  const rs     = data.run_summary   || {}
  const rm     = data.rag_retrieval || {}
  const passed = (rm.hit_rate || 0) >= 0.60

  const intentData = Object.entries(rm.per_intent || {})
    .map(([intent, rate]) => ({ intent: intent.replace(/_/g, ' '), rate: +(rate * 100).toFixed(1) }))
    .sort((a, b) => b.rate - a.rate)

  return (
    <div className="card">
      <h3 className="card-title">RAG Retrieval Evaluation</h3>

      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem', alignItems: 'center' }}>
        <div style={BADGE(passed)}>
          Hit Rate: {PCT(rm.hit_rate)} {passed ? '✓ PASS' : '✗ FAIL'}
        </div>
        <span style={{ color: '#7f8c8d', fontSize: '0.875rem' }}>threshold: 60%</span>
        <StatCard label="Emails"        value={rs.n_emails || '—'} />
        <StatCard label="Succeeded"     value={rs.n_succeeded || '—'} />
        <StatCard label="Avg Docs"      value={rm.avg_docs_retrieved != null ? rm.avg_docs_retrieved.toFixed(1) : '—'} />
        <StatCard label="Doc Precision" value={rm.avg_doc_precision != null ? PCT(rm.avg_doc_precision) : '—'} />
        <StatCard label="Empty Rate"    value={PCT(rm.empty_retrieval_rate)} />
        <StatCard label="Avg Latency"   value={rs.avg_latency_ms ? `${rs.avg_latency_ms}ms` : '—'} />
      </div>

      <h4 style={{ marginBottom: '0.75rem' }}>Per-Intent Hit Rate</h4>
      <ResponsiveContainer width="100%" height={250}>
        <BarChart data={intentData} layout="vertical" margin={{ left: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} />
          <YAxis type="category" dataKey="intent" width={175} tick={{ fontSize: 10 }} />
          <Tooltip formatter={v => `${v}%`} />
          <Bar dataKey="rate" fill="#fd7e14" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Response Generation ───────────────────────────────────────────────────────

function ResponseEval({ apiUrl, activeTab }) {
  const { data, loading, error } = useLazyFetch(`${apiUrl}/api/metrics/response-eval`, 'response', activeTab)

  return (
    <LoadState loading={loading} error={error}>
      {data ? <ResponseEvalContent data={data} /> : <NoData script="run_response_eval.py" />}
    </LoadState>
  )
}

function ResponseEvalContent({ data }) {
  const rg     = data.response_generation || {}
  const passed = (rg.escalation_agreement || 0) >= 0.70

  const intentData = Object.entries(rg.per_intent_f1 || {})
    .map(([intent, f1]) => ({ intent: intent.replace(/_/g, ' '), f1: +(f1 * 100).toFixed(1) }))
    .sort((a, b) => b.f1 - a.f1)

  return (
    <div className="card">
      <h3 className="card-title">Response Generation Evaluation</h3>

      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem', alignItems: 'center' }}>
        <div style={BADGE(passed)}>
          Escalation Agreement: {rg.escalation_agreement != null ? PCT(rg.escalation_agreement) : '—'}
          {' '}{passed ? '✓ PASS' : '✗ FAIL'}
        </div>
        <span style={{ color: '#7f8c8d', fontSize: '0.875rem' }}>threshold: 70%</span>
        <StatCard label="Avg LLM Score"  value={rg.avg_llm_judge_score != null ? rg.avg_llm_judge_score.toFixed(4) : '—'} sub={rg.judge_model ? 'Claude 3 Haiku' : ''} />
        <StatCard label="Hedge Rate"      value={PCT(rg.hedge_rate)} />
        <StatCard label="Coverage Rate"   value={PCT(rg.response_coverage_rate)} />
        <StatCard label="Evaluated"       value={rg.n_evaluated || '—'} />
        <StatCard label="With Gold Pair"  value={rg.n_with_gold_pair || '—'} />
      </div>

      {intentData.length > 0 && (
        <>
          <h4 style={{ marginBottom: '0.75rem' }}>Per-Intent Token-Overlap F1</h4>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={intentData} layout="vertical" margin={{ left: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} />
              <YAxis type="category" dataKey="intent" width={175} tick={{ fontSize: 10 }} />
              <Tooltip formatter={v => `${v}%`} />
              <Bar dataKey="f1" fill="#6f42c1" />
            </BarChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  )
}

// ── Reference Eval (existing) ─────────────────────────────────────────────────

function ReferenceEval({ apiUrl, activeTab }) {
  const { data, loading, error } = useLazyFetch(`${apiUrl}/api/metrics/evaluations`, 'reference', activeTab)

  return (
    <LoadState loading={loading} error={error}>
      {data ? <ReferenceEvalContent data={data} /> : <NoData script="reference_eval.py" />}
    </LoadState>
  )
}

function ReferenceEvalContent({ data }) {
  const refEval = data?.reference_eval || {}
  if (!refEval.aggregate) return (
    <div className="card">
      <h3 className="card-title">Reference Evaluation (RAG Pipeline)</h3>
      <p style={{ color: '#7f8c8d' }}>
        No reference eval report available. Run <code>scripts/reference_eval.py</code> to generate one.
      </p>
    </div>
  )

  const agg       = refEval.aggregate
  const results   = refEval.results || []
  const composite = agg.composite_score || 0
  const passed    = composite >= 0.75

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

      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
        <div style={BADGE(passed)}>
          Composite: {PCT(composite)} {passed ? '✓ PASS' : '✗ FAIL'}
        </div>
        <span style={{ color: '#7f8c8d', fontSize: '0.875rem' }}>
          Threshold: 75% &nbsp;|&nbsp; {agg.total} queries
        </span>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={aggData} barCategoryGap="30%">
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="metric" tick={{ fontSize: 12 }} />
          <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} />
          <Tooltip formatter={v => `${v}%`} />
          <Bar dataKey="value" fill="#667eea" />
        </BarChart>
      </ResponsiveContainer>

      <div className="table-container" style={{ marginTop: '1.5rem' }}>
        <table>
          <thead>
            <tr>
              <th>ID</th><th>Query</th><th>Recall</th><th>Hallucinated</th>
              <th>OOS Refused</th><th>Docs</th><th>Composite</th><th>Result</th>
            </tr>
          </thead>
          <tbody>
            {results.map(r => {
              const pass = r.composite >= 0.75
              return (
                <tr key={r.query_id}>
                  <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{r.query_id}</td>
                  <td title={r.query} style={{ maxWidth: '200px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', cursor: 'help' }}>
                    {r.query}
                  </td>
                  <td>{PCT(r.key_fact_recall)}</td>
                  <td><span style={{ padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.75rem', background: r.hallucination_flag ? '#f8d7da' : '#d4edda', color: r.hallucination_flag ? '#721c24' : '#155724' }}>{r.hallucination_flag ? 'Yes' : 'No'}</span></td>
                  <td><span style={{ padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.75rem', background: r.out_of_scope_refused ? '#d4edda' : '#fff3cd', color: r.out_of_scope_refused ? '#155724' : '#856404' }}>{r.out_of_scope_refused ? 'Yes' : 'No'}</span></td>
                  <td>{r.retrieved_docs}</td>
                  <td><strong>{PCT(r.composite)}</strong></td>
                  <td><span style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600, background: pass ? '#d4edda' : '#f8d7da', color: pass ? '#155724' : '#721c24' }}>{pass ? 'PASS' : 'FAIL'}</span></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function F1Badge({ v }) {
  const pct = v != null ? +(v * 100).toFixed(1) : null
  const bg = pct == null ? '#f8f9fa' : pct >= 80 ? '#d4edda' : pct >= 60 ? '#fff3cd' : '#f8d7da'
  const fg = pct == null ? '#6c757d' : pct >= 80 ? '#155724' : pct >= 60 ? '#856404' : '#721c24'
  return (
    <span style={{ padding: '0.1rem 0.4rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600, background: bg, color: fg }}>
      {pct != null ? `${pct}%` : '—'}
    </span>
  )
}

function MiniCard({ title, items }) {
  return (
    <div style={{ ...CARD, textAlign: 'left', minWidth: '160px' }}>
      <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.4rem' }}>{title}</div>
      {items.map((it, i) => (
        <div key={i} style={{ fontSize: '0.8rem', display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
          <span style={{ color: '#6c757d' }}>{it.label}</span>
          <span style={{ fontWeight: 600 }}>{it.value}</span>
        </div>
      ))}
    </div>
  )
}

function NoData({ script }) {
  return (
    <div className="card">
      <p style={{ color: '#7f8c8d', margin: 0 }}>
        No data available. Run <code>python scripts/{script}</code> first.
      </p>
    </div>
  )
}

export default Evaluations
