import React, { useState, useEffect } from 'react'
import axios from 'axios'

function RAGMetrics({ apiUrl }) {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [search, setSearch]   = useState('')

  useEffect(() => { fetchMetrics() }, [])

  const fetchMetrics = async () => {
    try {
      setLoading(true)
      const response = await axios.get(`${apiUrl}/api/metrics/rag`)
      setMetrics(response.data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading RAG metrics...</div>
  if (error)   return <div className="error">Error: {error}</div>
  if (!metrics) return null

  const chunksPerFile = metrics.chunks_per_file || {}
  const sortedFiles   = Object.entries(chunksPerFile)
    .sort((a, b) => b[1] - a[1])   // descending by chunk count
    .filter(([name]) => name.toLowerCase().includes(search.toLowerCase()))

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', fontSize: '1.75rem' }}>RAG Knowledge Base</h2>

      {/* ── Stats ── */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value">{metrics.total_chunks}</div>
          <div className="stat-label">Total Chunks</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{metrics.total_source_files}</div>
          <div className="stat-label">Source Files</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">
            {metrics.total_source_files > 0
              ? (metrics.total_chunks / metrics.total_source_files).toFixed(1)
              : '0'}
          </div>
          <div className="stat-label">Avg Chunks / File</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: metrics.status === 'active' ? '#28a745' : '#dc3545' }}>
            {metrics.status}
          </div>
          <div className="stat-label">Status</div>
        </div>
      </div>

      {/* ── File list ── */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 className="card-title" style={{ margin: 0 }}>Source Files ({sortedFiles.length})</h3>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter files…"
            style={{ padding: '0.4rem 0.7rem', borderRadius: 4, border: '1px solid #ddd', width: 220, fontSize: '0.85rem' }}
          />
        </div>
        <div className="table-container" style={{ maxHeight: 500, overflowY: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Source File</th>
                <th style={{ textAlign: 'right' }}>Chunks</th>
                <th style={{ textAlign: 'right' }}>% of KB</th>
              </tr>
            </thead>
            <tbody>
              {sortedFiles.map(([name, count], i) => (
                <tr key={name}>
                  <td style={{ color: '#aaa', fontSize: '0.8rem' }}>{i + 1}</td>
                  <td>
                    <code style={{ fontSize: '0.8rem', wordBreak: 'break-all' }}>{name}</code>
                  </td>
                  <td style={{ textAlign: 'right' }}>{count}</td>
                  <td style={{ textAlign: 'right', color: '#6c757d' }}>
                    {((count / metrics.total_chunks) * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── About ── */}
      <div className="card">
        <h3 className="card-title">About the RAG System</h3>
        <div style={{ lineHeight: 1.8 }}>
          <ul style={{ marginLeft: '1.5rem' }}>
            <li>Documents are chunked into 500-token segments with 50-token overlap</li>
            <li>Embeddings generated with Amazon Titan Embeddings (1 536 dimensions)</li>
            <li>Semantic search returns top-3 most relevant chunks per query</li>
            <li>Retrieved chunks ground the LLM response to prevent hallucination</li>
          </ul>
        </div>
      </div>
    </div>
  )
}

export default RAGMetrics
