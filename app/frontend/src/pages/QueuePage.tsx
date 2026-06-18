import { useState, useEffect, useRef, Fragment } from 'react'
import { Link } from 'react-router-dom'
import { getQueue, deleteQueueItem, clearQueuePending, clearQueueFailed, QueueItem } from '../api'


/** Derive active stage from progress string. */
function activeStage(progress: string | null): string | null {
  if (!progress) return null
  if (progress.startsWith('extracting')) return 'extract'
  if (progress.startsWith('cleanup')) return 'cleanup'
  if (progress.startsWith('summary')) return 'summary'
  return null
}

function shortUrl(url: string) {
  try {
    const u = new URL(url)
    const v = u.searchParams.get('v')
    if (v) return `youtu.be/${v}`
    return u.pathname.replace(/^\//, '')
  } catch {
    return url.slice(0, 40)
  }
}

function formatTime(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}, ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function QueuePage() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedError, setExpandedError] = useState<number | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function load() {
    try {
      const data = await getQueue()
      setItems(data.items)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // Always poll: 3s when active items present, 5s when idle (picks up new items added externally)
    pollRef.current = setInterval(load, 3000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleDelete(id: number) {
    try {
      await deleteQueueItem(id)
      setItems(prev => prev.filter(i => i.id !== id))
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete')
    }
  }

  async function handleClearPending() {
    if (!confirm('Clear all pending items?')) return
    try {
      const res = await clearQueuePending()
      if (res.cleared > 0) load()
    } catch {
      // ignore
    }
  }

  async function handleClearFailed() {
    if (!confirm('Remove all failed items?')) return
    try {
      const res = await clearQueueFailed()
      if (res.cleared > 0) setItems(prev => prev.filter(i => i.status !== 'failed'))
    } catch {
      // ignore
    }
  }

  const pendingCount = items.filter(i => i.status === 'pending').length
  const failedCount = items.filter(i => i.status === 'failed').length
  const processingItem = items.find(i => i.status === 'processing')

  const STATUS_ORDER: Record<string, number> = { processing: 0, pending: 1, failed: 2, done: 3, skipped: 4 }
  const sortedItems = [...items].sort((a, b) => {
    const sd = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9)
    if (sd !== 0) return sd
    // Within same status: newest first
    return new Date(b.added_at).getTime() - new Date(a.added_at).getTime()
  })

  return (
    <div className="p-6 md:p-gutter max-w-[1200px] mx-auto w-full">
      <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm overflow-hidden flex flex-col mb-12">

        {/* Header */}
        <div className="p-6 flex justify-between items-center border-b border-outline-variant">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary" style={{ fontSize: '24px' }}>timer</span>
            <h2 className="text-headline-lg text-on-surface font-bold">Processing Queue</h2>
          </div>
          <div className="flex gap-3">
            {failedCount > 0 && (
              <button
                className="px-4 py-2 border border-error text-error rounded-lg text-label-md font-semibold hover:bg-error-container transition-colors active:scale-95"
                onClick={handleClearFailed}
              >
                Clean failed ({failedCount})
              </button>
            )}
            {pendingCount > 0 && (
              <button
                className="px-4 py-2 bg-surface-container-high text-on-surface-variant rounded-lg text-label-md font-semibold hover:bg-surface-container-highest transition-colors active:scale-95"
                onClick={handleClearPending}
              >
                Clear pending ({pendingCount})
              </button>
            )}
            <Link
              to="/"
              className="px-4 py-2 bg-surface-container-high text-on-surface-variant rounded-lg text-label-md font-semibold hover:bg-surface-container-highest transition-colors flex items-center gap-2"
            >
              <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>keyboard_backspace</span>
              Home
            </Link>
          </div>
        </div>

        {loading && (
          <div className="p-12 text-center text-secondary text-body-md">Loading…</div>
        )}

        {!loading && items.length === 0 && (
          <div className="p-12 text-center text-secondary text-body-md">
            No items in queue. <Link to="/" className="text-primary hover:underline">Add videos →</Link>
          </div>
        )}

        {!loading && items.length > 0 && (
          <>
            {/* Active processing banner */}
            {processingItem && (
              <div className="px-6 py-4 bg-secondary-container/30 border-b border-outline-variant">
                <div className="flex items-center gap-4 text-body-md flex-wrap">
                  <span className="material-symbols-outlined text-secondary" style={{ animation: 'spin 1.5s linear infinite' }}>sync</span>
                  <span className="font-medium">
                    Processing: <span className="text-primary font-semibold">{shortUrl(processingItem.url)}</span>
                  </span>
                  <div className="flex items-center gap-2 text-on-surface-variant text-body-sm">
                    {processingItem.pipeline_stages.map((s, i) => {
                      const cur = activeStage(processingItem.progress)
                      const curIdx = cur ? processingItem.pipeline_stages.indexOf(cur) : -1
                      const isActive = cur === s
                      const isDone = curIdx > i
                      return (
                        <span key={s} className="flex items-center gap-2">
                          {i > 0 && <span className="material-symbols-outlined text-outline" style={{ fontSize: '14px' }}>arrow_forward</span>}
                          <span className={isActive ? 'text-primary font-bold' : isDone ? 'text-tertiary' : 'text-on-surface-variant'}>{s}</span>
                        </span>
                      )
                    })}
                  </div>
                  {processingItem.progress && (
                    <span className="ml-auto text-secondary italic text-body-sm">{processingItem.progress}</span>
                  )}
                </div>
              </div>
            )}

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant">
                    <th className="px-6 py-4 text-label-sm text-on-surface-variant uppercase tracking-wider">#</th>
                    <th className="px-6 py-4 text-label-sm text-on-surface-variant uppercase tracking-wider">URL</th>
                    <th className="px-6 py-4 text-label-sm text-on-surface-variant uppercase tracking-wider">Pipeline</th>
                    <th className="px-6 py-4 text-label-sm text-on-surface-variant uppercase tracking-wider text-center">Status</th>
                    <th className="px-6 py-4 text-label-sm text-on-surface-variant uppercase tracking-wider text-right">Added</th>
                    <th className="px-6 py-4"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant/30">
                  {sortedItems.map((item, idx) => {
                    const rowBg =
                      item.status === 'processing' ? 'bg-secondary-container/10 hover:bg-surface-container-high' :
                      item.status === 'failed' ? 'bg-error-container/5 hover:bg-error-container/20' :
                      'hover:bg-surface-container-high'
                    return (
                      <Fragment key={item.id}>
                        <tr className={`transition-colors ${rowBg}`}>
                          <td className="px-6 py-5 text-on-surface-variant text-label-md">{idx + 1}</td>
                          <td className="px-6 py-5 text-label-md">
                            {item.status === 'done' && item.video_id ? (
                              <Link to={`/result/${item.video_id}`} className="text-primary font-medium hover:underline">{shortUrl(item.url)}</Link>
                            ) : (
                              <span className="text-primary font-medium" title={item.url}>{shortUrl(item.url)}</span>
                            )}
                          </td>
                          <td className="px-6 py-5">
                            <div className="flex items-center gap-1 text-label-sm">
                              {item.pipeline_stages.map((s, i) => {
                                const cur = item.status === 'processing' ? activeStage(item.progress) : null
                                const curIdx = cur ? item.pipeline_stages.indexOf(cur) : -1
                                const isActive = cur === s
                                const isDone = item.status === 'done' || (curIdx > i)
                                return (
                                  <span key={s} className="flex items-center gap-1">
                                    {i > 0 && <span className="text-outline">→</span>}
                                    <span className={
                                      isActive ? 'text-primary font-bold' :
                                      isDone ? 'text-tertiary' :
                                      'text-on-surface-variant'
                                    }>{s}</span>
                                  </span>
                                )
                              })}
                            </div>
                          </td>
                          <td className="px-6 py-5">
                            <div className={`flex items-center justify-center gap-2 font-semibold text-body-sm ${
                              item.status === 'processing' ? 'text-secondary' :
                              item.status === 'done' ? 'text-tertiary' :
                              item.status === 'failed' ? 'text-error' :
                              'text-on-surface-variant'
                            }`}>
                              {item.status === 'processing' && <span className="material-symbols-outlined" style={{ fontSize: '18px', animation: 'spin 1.5s linear infinite' }}>hourglass_top</span>}
                              {item.status === 'done' && <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>check_circle</span>}
                              {item.status === 'failed' && <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>error</span>}
                              {item.status === 'pending' && <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>schedule</span>}
                              <span>{item.status}</span>
                              {item.status === 'failed' && item.error_message && (
                                <button onClick={() => setExpandedError(expandedError === item.id ? null : item.id)}>
                                  <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>
                                    {expandedError === item.id ? 'expand_less' : 'expand_more'}
                                  </span>
                                </button>
                              )}
                            </div>
                            {item.status === 'processing' && item.progress && (
                              <div className="text-center text-body-sm text-secondary mt-1 italic">{item.progress}</div>
                            )}
                          </td>
                          <td className="px-6 py-5 text-right text-on-surface-variant text-label-sm">{formatTime(item.added_at)}</td>
                          <td className="px-6 py-5 text-right">
                            {item.status === 'pending' && (
                              <button
                                className="text-on-surface-variant hover:text-error transition-colors"
                                title="Remove from queue"
                                onClick={() => handleDelete(item.id)}
                              >
                                <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>close</span>
                              </button>
                            )}
                          </td>
                        </tr>
                        {expandedError === item.id && item.error_message && (
                          <tr>
                            <td colSpan={6} className="px-6 py-3 bg-error-container/10">
                              <div className="text-error text-body-sm font-mono whitespace-pre-wrap">{item.error_message}</div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
