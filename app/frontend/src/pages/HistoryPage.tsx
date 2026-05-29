import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { getHistory, deleteResult, deleteResultsBulk, queueBulkAdd, HistoryItem } from '../api'
import { classifyVideo } from '../utils/videoType'

const HISTORY_PIPELINE_PRESETS = [
  { value: 'cleanup', label: 'Cleanup', stages: ['cleanup'] },
  { value: 'summary', label: 'Summary', stages: ['summary'] },
  { value: 'cleanup_summary', label: 'Cleanup + Summary', stages: ['cleanup', 'summary'] },
]

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState('')
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [queuePipeline, setQueuePipeline] = useState('cleanup_summary')
  const [queueMsg, setQueueMsg] = useState<string | null>(null)
  const navigate = useNavigate()

  async function load(p: number) {
    try {
      const res = await getHistory(p)
      setItems(prev => p === 1 ? res.items : [...prev, ...res.items])
      setHasMore(res.items.length === 20)
      setPage(p)
    } catch (err) {
      console.error('[History] getHistory failed:', err)
      setError('Failed to load history')
    }
  }

  useEffect(() => { load(1) }, [])

  function toggleSelectMode() {
    setSelectMode(m => !m)
    setSelected(new Set())
    setQueueMsg(null)
  }

  function toggleItem(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function selectAll() {
    setSelected(new Set(items.map(i => i.video_id)))
  }

  function deselectAll() {
    setSelected(new Set())
  }

  async function handleDelete(videoId: string) {
    if (!window.confirm('Delete this video and all its data? This cannot be undone.')) return
    try {
      await deleteResult(videoId)
      setItems(prev => prev.filter(i => i.video_id !== videoId))
    } catch (err) {
      console.error('[History] deleteResult failed:', err)
    }
  }

  async function handleBulkQueue() {
    const ids = Array.from(selected)
    if (!ids.length) return
    const preset = HISTORY_PIPELINE_PRESETS.find(p => p.value === queuePipeline)
    const stages = preset?.stages ?? ['cleanup', 'summary']
    // Get URLs for selected video_ids
    const urls = items
      .filter(i => selected.has(i.video_id))
      .map(i => `https://www.youtube.com/watch?v=${i.video_id}`)
    try {
      const res = await queueBulkAdd(urls, stages, true) // force=true skips dedup
      setQueueMsg(`Added ${res.added} video${res.added !== 1 ? 's' : ''} to queue`)
      setSelected(new Set())
      setSelectMode(false)
    } catch (err) {
      setQueueMsg('Failed to add to queue')
    }
  }

  async function handleBulkDelete() {
    const ids = Array.from(selected)
    if (!ids.length) return
    if (!window.confirm(`Delete ${ids.length} video${ids.length !== 1 ? 's' : ''} and all their data? This cannot be undone.`)) return
    setDeleting(true)
    try {
      await deleteResultsBulk(ids)
      setItems(prev => prev.filter(i => !selected.has(i.video_id)))
      setSelected(new Set())
      setSelectMode(false)
    } catch (err) {
      console.error('[History] bulkDelete failed:', err)
    } finally {
      setDeleting(false)
    }
  }

  if (error) return (
    <div className="container">
      <div className="card"><div className="error-box">{error}</div></div>
    </div>
  )

  const allSelected = items.length > 0 && selected.size === items.length

  return (
    <div className="container">
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h2 style={{ margin: 0 }}>History</h2>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            {selectMode && (
              <>
                <button className="btn btn-secondary btn-sm" onClick={allSelected ? deselectAll : selectAll}>
                  {allSelected ? 'Deselect all' : 'Select all'}
                </button>
                <select
                  className="btn-sm"
                  style={{ padding: '0.3rem 0.5rem', fontSize: '0.82rem', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface-2)', color: 'var(--text)' }}
                  value={queuePipeline}
                  onChange={e => setQueuePipeline(e.target.value)}
                  disabled={selected.size === 0}
                >
                  {HISTORY_PIPELINE_PRESETS.map(p => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={selected.size === 0}
                  onClick={handleBulkQueue}
                  title="Add selected to processing queue"
                >
                  ⏱ Queue ({selected.size})
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  disabled={selected.size === 0 || deleting}
                  onClick={handleBulkDelete}
                >
                  {deleting ? 'Deleting…' : `Delete (${selected.size})`}
                </button>
                <button className="btn btn-secondary btn-sm" onClick={toggleSelectMode}>Cancel</button>
              </>
            )}
            {!selectMode && items.length > 0 && (
              <button className="btn btn-secondary btn-sm" onClick={toggleSelectMode}>Select</button>
            )}
          </div>
        </div>

        {queueMsg && (
          <div className="bulk-result bulk-result--ok" style={{ marginBottom: '0.75rem' }}>
            {queueMsg} — <Link to="/queue">View queue →</Link>
          </div>
        )}

        {items.length === 0 ? (
          <div className="empty">No videos processed yet.</div>
        ) : (
          <ul className="history-list">
            {items.map(item => {
              const type = classifyVideo(item.char_count, item.has_chapters)
              const isSelected = selected.has(item.video_id)
              return (
                <li
                  key={item.video_id}
                  className={`history-item${isSelected ? ' history-item--selected' : ''}`}
                >
                  <div
                    className="history-info"
                    onClick={() => selectMode ? toggleItem(item.video_id) : navigate(`/result/${item.video_id}`)}
                    style={{ cursor: 'pointer' }}
                  >
                    <div className="history-title">{item.title ?? 'Untitled'}</div>
                    <div className="history-meta">
                      {item.author && <>{item.author} · </>}
                      {new Date(item.created_at).toLocaleDateString()}
                      {item.char_count && <> · {item.char_count.toLocaleString()} chars</>}
                    </div>
                  </div>
                  <div className="stage-checks">
                    <span
                      className={`stage-check ${item.has_cleaned ? 'stage-check--done' : 'stage-check--off'}`}
                      title={item.has_cleaned ? 'AI Cleanup: done' : 'AI Cleanup: not run'}
                    >✓</span>
                    <span
                      className={`stage-check ${item.has_summary ? 'stage-check--done' : 'stage-check--off'}`}
                      title={item.has_summary ? 'Summary: done' : 'Summary: not run'}
                    >✓</span>
                  </div>
                  {type && (
                    <span className={`type-badge type-${type.key}`} title={`Auto-mode: ${type.mode}`}>
                      {type.emoji} {type.label}
                    </span>
                  )}
                  {item.language && <span className="lang-badge">{item.language.toUpperCase()}</span>}
                  {!selectMode && (
                    <button
                      className="btn btn-danger"
                      style={{ padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}
                      onClick={() => handleDelete(item.video_id)}
                    >
                      Delete
                    </button>
                  )}
                  {selectMode && (
                    <input
                      type="checkbox"
                      className="history-checkbox"
                      checked={isSelected}
                      onChange={() => toggleItem(item.video_id)}
                    />
                  )}
                </li>
              )
            })}
          </ul>
        )}
        {hasMore && (
          <button className="btn btn-secondary" style={{ marginTop: '1rem' }} onClick={() => load(page + 1)}>
            Load more
          </button>
        )}
      </div>
    </div>
  )
}
