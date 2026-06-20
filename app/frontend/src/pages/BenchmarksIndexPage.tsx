import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAllBenchmarks, BenchmarkGroup } from '../api'

function formatDate(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}, ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function BenchmarksIndexPage() {
  const [groups, setGroups]   = useState<BenchmarkGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
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

  return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto">
      <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm overflow-hidden">

        {/* Header */}
        <div className="p-6 border-b border-outline-variant flex items-center gap-3">
          <span className="material-symbols-outlined text-primary text-[28px]">speed</span>
          <h2 className="text-headline-lg font-bold text-on-surface">Benchmarks</h2>
        </div>

        {/* Loading */}
        {loading && (
          <div className="py-16 text-center text-secondary text-body-md">Loading…</div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="p-6">
            <div className="flex items-start gap-3 p-4 bg-error-container/20 border border-error/30 rounded-lg">
              <span className="material-symbols-outlined text-error text-[18px] mt-0.5">warning</span>
              <span className="text-body-sm text-on-error-container">{error}</span>
            </div>
          </div>
        )}

        {/* Empty */}
        {!loading && !error && groups.length === 0 && (
          <div className="py-16 text-center">
            <span className="material-symbols-outlined text-[48px] text-outline-variant block mb-3">speed</span>
            <p className="text-body-md text-secondary max-w-sm mx-auto">
              No benchmarks yet. Open any video from History and click ⚖ Benchmark to start.
            </p>
          </div>
        )}

        {/* List */}
        {!loading && !error && groups.length > 0 && (
          <div className="divide-y divide-outline-variant">
            {groups.map(g => (
              <div
                key={g.video_id}
                className="flex items-center gap-4 px-6 py-5 hover:bg-surface-container-low transition-colors cursor-pointer group"
                onClick={() => navigate(`/benchmark/${g.video_id}`)}
              >
                <span className="material-symbols-outlined text-secondary text-[22px] flex-shrink-0">speed</span>

                <div className="flex-1 min-w-0">
                  <h3 className="text-body-md font-semibold text-on-surface truncate">
                    {g.title ?? g.video_id}
                  </h3>
                  <p className="text-body-sm text-secondary mt-0.5">
                    {g.total_runs} run{g.total_runs !== 1 ? 's' : ''}
                    {' · '}
                    {g.models.length} model{g.models.length !== 1 ? 's' : ''} ({g.models.join(', ')})
                    {' · '}
                    {formatDate(g.latest_run_at)}
                  </p>
                </div>

                <span className="material-symbols-outlined text-[18px] text-outline-variant group-hover:text-primary transition-colors flex-shrink-0">
                  chevron_right
                </span>
              </div>
            ))}
          </div>
        )}

      </div>
    </div>
  )
}
