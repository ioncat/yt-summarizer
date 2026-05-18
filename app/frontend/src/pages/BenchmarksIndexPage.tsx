import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAllBenchmarks, BenchmarkGroup } from '../api'

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function BenchmarksIndexPage() {
  const [groups, setGroups] = useState<BenchmarkGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    getAllBenchmarks()
      .then(setGroups)
      .catch(err => {
        console.error('[Benchmarks] load failed:', err)
        setError('Failed to load benchmarks')
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="container"><div className="card">Loading…</div></div>
  )

  if (error) return (
    <div className="container">
      <div className="card"><div className="error-box">{error}</div></div>
    </div>
  )

  return (
    <div className="container">
      <div className="card">
        <h2>Benchmarks</h2>
        {groups.length === 0 ? (
          <p style={{ color: '#888', padding: '2rem 0', textAlign: 'center' }}>
            No benchmarks yet. Open any video from History and click ⚖ Benchmark to start.
          </p>
        ) : (
          <ul className="history-list">
            {groups.map(g => (
              <li
                key={g.video_id}
                className="history-item"
                onClick={() => navigate(`/benchmark/${g.video_id}`)}
                style={{ cursor: 'pointer' }}
              >
                <div className="history-info">
                  <div className="history-title">{g.title ?? g.video_id}</div>
                  <div className="history-meta">
                    {g.total_runs} run{g.total_runs !== 1 ? 's' : ''} · {g.models.length} model{g.models.length !== 1 ? 's' : ''} ({g.models.join(', ')}) · {formatDate(g.latest_run_at)}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
