import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { getQueue, deleteQueueItem, clearQueuePending, QueueItem } from '../api'

const STATUS_ICON: Record<string, string> = {
  pending: '⏸',
  processing: '⏳',
  done: '✓',
  failed: '✗',
  skipped: '—',
}

const STATUS_CLASS: Record<string, string> = {
  pending: 'queue-status--pending',
  processing: 'queue-status--processing',
  done: 'queue-status--done',
  failed: 'queue-status--failed',
  skipped: 'queue-status--skipped',
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
    pollRef.current = setInterval(() => {
      const hasActive = items.some(i => i.status === 'pending' || i.status === 'processing')
      if (hasActive) load()
    }, 3000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Re-register poll when items change (to pick up new active state)
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    const hasActive = items.some(i => i.status === 'pending' || i.status === 'processing')
    if (hasActive) {
      pollRef.current = setInterval(load, 3000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [items])

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

  const pendingCount = items.filter(i => i.status === 'pending').length
  const processingItem = items.find(i => i.status === 'processing')

  return (
    <div className="container">
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <h2 style={{ margin: 0 }}>⏱ Processing Queue</h2>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {pendingCount > 0 && (
              <button className="btn btn-secondary btn-sm" onClick={handleClearPending}>
                Clear pending ({pendingCount})
              </button>
            )}
            <Link to="/" className="btn btn-secondary btn-sm">← Home</Link>
          </div>
        </div>

        {loading && <div className="empty">Loading…</div>}

        {!loading && items.length === 0 && (
          <div className="empty">No items in queue. <Link to="/">Add videos →</Link></div>
        )}

        {!loading && items.length > 0 && (
          <div className="queue-list">
            {processingItem && (
              <div className="queue-processing-banner">
                <span className="tab-spinner" style={{ marginRight: '0.5rem' }} />
                Processing: <strong>{shortUrl(processingItem.url)}</strong>
                {processingItem.pipeline_stages.length > 0 && (
                  <span className="meta-chip" style={{ marginLeft: '0.5rem' }}>
                    {processingItem.pipeline_stages.join(' → ')}
                  </span>
                )}
              </div>
            )}

            <table className="queue-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>URL</th>
                  <th>Pipeline</th>
                  <th>Status</th>
                  <th>Added</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, idx) => (
                  <>
                    <tr key={item.id} className={`queue-row queue-row--${item.status}`}>
                      <td className="queue-cell-num">{idx + 1}</td>
                      <td className="queue-cell-url">
                        {item.status === 'done' && item.video_id ? (
                          <Link to={`/result/${item.video_id}`}>{shortUrl(item.url)}</Link>
                        ) : (
                          <span title={item.url}>{shortUrl(item.url)}</span>
                        )}
                      </td>
                      <td className="queue-cell-pipeline">
                        {item.pipeline_stages.join(' → ')}
                      </td>
                      <td className="queue-cell-status">
                        <span className={`queue-status ${STATUS_CLASS[item.status] ?? ''}`}>
                          {STATUS_ICON[item.status] ?? item.status} {item.status}
                        </span>
                        {item.status === 'failed' && item.error_message && (
                          <button
                            className="queue-error-toggle"
                            onClick={() => setExpandedError(expandedError === item.id ? null : item.id)}
                          >
                            {expandedError === item.id ? '▲' : '▼'}
                          </button>
                        )}
                      </td>
                      <td className="queue-cell-time">{formatTime(item.added_at)}</td>
                      <td className="queue-cell-actions">
                        {item.status === 'pending' && (
                          <button
                            className="queue-delete-btn"
                            title="Remove from queue"
                            onClick={() => handleDelete(item.id)}
                          >
                            ✕
                          </button>
                        )}
                        {item.status === 'processing' && (
                          <span className="queue-delete-btn queue-delete-btn--disabled" title="Cannot remove while processing">✕</span>
                        )}
                      </td>
                    </tr>
                    {expandedError === item.id && item.error_message && (
                      <tr key={`err-${item.id}`} className="queue-row-error">
                        <td colSpan={6}>
                          <div className="queue-error-msg">{item.error_message}</div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
