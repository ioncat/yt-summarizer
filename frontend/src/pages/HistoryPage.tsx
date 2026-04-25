import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getHistory, deleteResult, HistoryItem } from '../api'

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  async function load(p: number) {
    try {
      const res = await getHistory(p)
      setItems(prev => p === 1 ? res.items : [...prev, ...res.items])
      setHasMore(res.items.length === 20)
      setPage(p)
    } catch {
      setError('Failed to load history')
    }
  }

  useEffect(() => { load(1) }, [])

  async function handleDelete(videoId: string) {
    await deleteResult(videoId)
    setItems(prev => prev.filter(i => i.video_id !== videoId))
  }

  if (error) return (
    <div className="container">
      <div className="card"><div className="error-box">{error}</div></div>
    </div>
  )

  return (
    <div className="container">
      <div className="card">
        <h2>History</h2>
        {items.length === 0 ? (
          <div className="empty">No videos processed yet.</div>
        ) : (
          <ul className="history-list">
            {items.map(item => (
              <li key={item.video_id} className="history-item">
                <div className="history-info" onClick={() => navigate(`/result/${item.video_id}`)} style={{ cursor: 'pointer' }}>
                  <div className="history-title">{item.title ?? 'Untitled'}</div>
                  <div className="history-meta">
                    {item.author && <>{item.author} · </>}
                    {new Date(item.created_at).toLocaleDateString()}
                    {item.char_count && <> · {item.char_count.toLocaleString()} chars</>}
                  </div>
                </div>
                {item.language && <span className="lang-badge">{item.language.toUpperCase()}</span>}
                <button className="btn btn-danger" style={{ padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}
                  onClick={() => handleDelete(item.video_id)}>
                  Delete
                </button>
              </li>
            ))}
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
