import { useState, useEffect, useRef, Fragment } from 'react'
import { Link } from 'react-router-dom'
import { getQueue, deleteQueueItem, clearQueuePending, clearQueueFailed, QueueItem } from '../api'

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

const STATUS_ORDER: Record<string, number> = { processing: 0, pending: 1, failed: 2, done: 3, skipped: 4 }

export default function QueuePage() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedError, setExpandedError] = useState<number | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function load() {
    try {
      const data = await getQueue()
      setItems(data.items)
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
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
    } catch { /* ignore */ }
  }

  async function handleClearFailed() {
    if (!confirm('Remove all failed items?')) return
    try {
      const res = await clearQueueFailed()
      if (res.cleared > 0) setItems(prev => prev.filter(i => i.status !== 'failed'))
    } catch { /* ignore */ }
  }

  const pendingCount = items.filter(i => i.status === 'pending').length
  const failedCount  = items.filter(i => i.status === 'failed').length
  const processingItem = items.find(i => i.status === 'processing')

  const sortedItems = [...items].sort((a, b) => {
    const sd = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9)
    if (sd !== 0) return sd
    return new Date(b.added_at).getTime() - new Date(a.added_at).getTime()
  })

  return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto">
      <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm overflow-hidden">

        {/* Header */}
        <div className="p-6 flex justify-between items-center border-b border-outline-variant">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-[28px]">timer</span>
            <h2 className="text-headline-lg font-bold text-on-surface">Processing Queue</h2>
          </div>
          <div className="flex gap-3 flex-wrap">
            {failedCount > 0 && (
              <button
                onClick={handleClearFailed}
                className="px-4 py-2 border border-error text-error rounded-lg text-label-md font-semibold hover:bg-error-container transition-colors"
              >
                Clean failed ({failedCount})
              </button>
            )}
            {pendingCount > 0 && (
              <button
                onClick={handleClearPending}
                className="px-4 py-2 bg-surface-container-high text-on-surface-variant rounded-lg text-label-md font-semibold hover:bg-surface-container-highest transition-colors"
              >
                Clear pending ({pendingCount})
              </button>
            )}
            <Link
              to="/"
              className="px-4 py-2 bg-surface-container-high text-on-surface-variant rounded-lg text-label-md font-semibold hover:bg-surface-container-highest transition-colors flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-[18px]">keyboard_backspace</span>
              Home
            </Link>
          </div>
        </div>

        {/* Processing banner */}
        {processingItem && (
          <div className="px-6 py-4 bg-secondary-container/30 border-b border-outline-variant">
            <div className="flex items-center gap-4 text-body-md flex-wrap">
              <span className="material-symbols-outlined text-secondary pulse-dot">sync</span>
              <span className="font-medium text-on-surface">
                Processing:{' '}
                <span className="text-primary font-semibold">{shortUrl(processingItem.url)}</span>
              </span>
              {processingItem.pipeline_stages.length > 0 && (
                <div className="flex items-center gap-1 text-label-sm">
                  {processingItem.pipeline_stages.map((s, i) => {
                    const cur = activeStage(processingItem.progress)
                    const isActive = cur === s
                    return (
                      <span key={s} className="flex items-center gap-1">
                        {i > 0 && (
                          <span className="material-symbols-outlined text-[14px] text-outline">arrow_forward</span>
                        )}
                        <span className={isActive ? 'text-primary font-bold' : 'text-on-surface-variant'}>
                          {s}
                        </span>
                      </span>
                    )
                  })}
                </div>
              )}
              {processingItem.progress && (
                <span className="ml-auto text-secondary italic text-body-sm">{processingItem.progress}</span>
              )}
            </div>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="py-16 text-center text-secondary text-body-md">Loading…</div>
        )}

        {/* Empty */}
        {!loading && items.length === 0 && (
          <div className="py-16 text-center">
            <span className="material-symbols-outlined text-[48px] text-outline-variant block mb-3">inbox</span>
            <p className="text-body-md text-secondary">
              Queue is empty.{' '}
              <Link to="/" className="text-primary font-semibold hover:underline">Add videos →</Link>
            </p>
          </div>
        )}

        {/* Table */}
        {!loading && items.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant">
                    <th className="px-6 py-4 text-label-sm font-bold text-on-surface-variant uppercase tracking-wider">#</th>
                    <th className="px-6 py-4 text-label-sm font-bold text-on-surface-variant uppercase tracking-wider">URL</th>
                    <th className="px-6 py-4 text-label-sm font-bold text-on-surface-variant uppercase tracking-wider">Pipeline</th>
                    <th className="px-6 py-4 text-label-sm font-bold text-on-surface-variant uppercase tracking-wider text-center">Status</th>
                    <th className="px-6 py-4 text-label-sm font-bold text-on-surface-variant uppercase tracking-wider text-right">Added</th>
                    <th className="px-6 py-4 w-10" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant/30">
                  {sortedItems.map((item, idx) => (
                    <Fragment key={item.id}>
                      <tr className={`transition-colors ${
                        item.status === 'processing' ? 'bg-secondary-container/10 hover:bg-secondary-container/20'
                        : item.status === 'failed'   ? 'bg-error-container/5 hover:bg-error-container/20'
                        : 'hover:bg-surface-container-high'
                      }`}>
                        <td className="px-6 py-5 text-on-surface-variant text-body-sm">{idx + 1}</td>

                        {/* URL */}
                        <td className="px-6 py-5 text-body-sm">
                          {item.status === 'done' && item.video_id ? (
                            <Link to={`/result/${item.video_id}`} className="text-primary font-medium hover:underline">
                              {shortUrl(item.url)}
                            </Link>
                          ) : (
                            <span className="text-primary font-medium" title={item.url}>{shortUrl(item.url)}</span>
                          )}
                        </td>

                        {/* Pipeline */}
                        <td className="px-6 py-5">
                          <div className="flex items-center gap-1 text-label-sm flex-wrap">
                            {item.pipeline_stages.map((s, i) => {
                              const cur = item.status === 'processing' ? activeStage(item.progress) : null
                              const curIdx = cur ? item.pipeline_stages.indexOf(cur) : -1
                              const isActive = cur === s
                              const isDone = curIdx > -1 && curIdx > i
                              return (
                                <span key={s} className="flex items-center gap-1">
                                  {i > 0 && <span className="text-outline text-[12px]">→</span>}
                                  <span className={
                                    isActive ? 'text-primary font-bold'
                                    : isDone  ? 'text-tertiary'
                                    : 'text-on-surface-variant'
                                  }>{s}</span>
                                </span>
                              )
                            })}
                          </div>
                        </td>

                        {/* Status */}
                        <td className="px-6 py-5">
                          <div className="flex items-center justify-center gap-1.5">
                            {item.status === 'processing' && (
                              <>
                                <span className="material-symbols-outlined text-[18px] text-secondary pulse-dot">hourglass_top</span>
                                <span className="text-secondary font-semibold text-body-sm">processing</span>
                              </>
                            )}
                            {item.status === 'pending' && (
                              <>
                                <span className="material-symbols-outlined text-[18px] text-on-surface-variant">schedule</span>
                                <span className="text-on-surface-variant font-semibold text-body-sm">pending</span>
                              </>
                            )}
                            {item.status === 'done' && (
                              <>
                                <span className="material-symbols-outlined text-[18px] text-tertiary">check_circle</span>
                                <span className="text-tertiary font-semibold text-body-sm">done</span>
                              </>
                            )}
                            {item.status === 'failed' && (
                              <>
                                <span className="material-symbols-outlined text-[18px] text-error">error</span>
                                <span className="text-error font-semibold text-body-sm">failed</span>
                                {item.error_message && (
                                  <button
                                    onClick={() => setExpandedError(expandedError === item.id ? null : item.id)}
                                    className="material-symbols-outlined text-[16px] text-error hover:text-on-surface transition-colors"
                                  >
                                    {expandedError === item.id ? 'expand_less' : 'expand_more'}
                                  </button>
                                )}
                              </>
                            )}
                            {item.status === 'skipped' && (
                              <span className="text-on-surface-variant text-body-sm">skipped</span>
                            )}
                          </div>
                          {item.status === 'processing' && item.progress && (
                            <p className="text-label-sm text-secondary text-center mt-1 opacity-80">{item.progress}</p>
                          )}
                        </td>

                        {/* Added */}
                        <td className="px-6 py-5 text-right text-on-surface-variant text-label-sm whitespace-nowrap">
                          {formatTime(item.added_at)}
                        </td>

                        {/* Actions */}
                        <td className="px-6 py-5 text-center">
                          {item.status === 'pending' && (
                            <button
                              onClick={() => handleDelete(item.id)}
                              title="Remove from queue"
                              className="material-symbols-outlined text-[18px] text-outline hover:text-error transition-colors"
                            >
                              close
                            </button>
                          )}
                        </td>
                      </tr>

                      {/* Error expansion */}
                      {expandedError === item.id && item.error_message && (
                        <tr className="bg-error-container/10">
                          <td colSpan={6} className="px-6 py-3">
                            <p className="text-body-sm text-error font-mono whitespace-pre-wrap break-all">
                              {item.error_message}
                            </p>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Footer */}
            <div className="px-6 py-4 bg-surface-container-low border-t border-outline-variant">
              <span className="text-label-sm text-on-surface-variant">
                Showing {items.length} item{items.length !== 1 ? 's' : ''}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
