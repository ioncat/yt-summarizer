import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getHistory, deleteResult, deleteResultsBulk, HistoryItem } from '../api'
import { classifyVideo } from '../utils/videoType'

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState('')
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [deleting, setDeleting] = useState(false)
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
                  {selectMode && (
                    <input
                      type="checkbox"
                      className="history-checkbox"
                      checked={isSelected}
                      onChange={() => toggleItem(item.video_id)}
                    />
                  )}
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
