import { useEffect, useState, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { getHistory, deleteResult, deleteResultsBulk, queueBulkAdd, toggleFavorite, HistoryItem } from '../api'
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
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [favoritesOnly, setFavoritesOnly] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const navigate = useNavigate()

  async function load(p: number, q?: string, favs?: boolean) {
    try {
      const res = await getHistory(p, q ?? search, favs ?? favoritesOnly)
      setItems(prev => p === 1 ? res.items : [...prev, ...res.items])
      setHasMore(res.items.length === 20)
      setPage(p)
    } catch (err) {
      console.error('[History] getHistory failed:', err)
      setError('Failed to load history')
    }
  }

  useEffect(() => { load(1) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function handleSearchChange(val: string) {
    setSearchInput(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearch(val)
      load(1, val)
    }, 350)
  }

  function toggleFavoritesFilter() {
    const next = !favoritesOnly
    setFavoritesOnly(next)
    load(1, search, next)
  }

  async function handleToggleFavorite(e: React.MouseEvent, videoId: string) {
    e.stopPropagation()
    try {
      const r = await toggleFavorite(videoId)
      if (favoritesOnly && !r.is_favorite) {
        setItems(prev => prev.filter(i => i.video_id !== videoId))
      } else {
        setItems(prev => prev.map(i => i.video_id === videoId ? { ...i, is_favorite: r.is_favorite } : i))
      }
    } catch { /* ignore */ }
  }

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
    <div className="p-gutter max-w-[1200px] mx-auto py-8">
      <div className="bg-error-container text-on-error-container rounded-xl px-6 py-4 text-body-md">{error}</div>
    </div>
  )

  const allSelected = items.length > 0 && selected.size === items.length

  function typeBadgeClass(key: string) {
    if (key === 'xl') return 'bg-error-container text-on-error-container'
    if (key === 'long_structured') return 'bg-secondary-container text-on-secondary-container'
    return 'bg-surface-container-high text-on-surface-variant'
  }

  function typeIcon(key: string) {
    if (key === 'xl') return 'menu_book'
    if (key === 'long_structured') return 'article'
    if (key === 'long') return 'article'
    return 'description'
  }

  return (
    <div className="p-6 md:p-gutter max-w-[1200px] mx-auto py-8 w-full">
      <div className="bg-surface-container-lowest rounded-xl shadow-sm border border-outline-variant overflow-hidden">

        {/* Card header */}
        <div className="p-6 border-b border-outline-variant space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="text-headline-xl text-on-surface">History</h2>
            <div className="flex items-center gap-2">
              {selectMode ? (
                <>
                  <button
                    className="bg-surface-container-high text-secondary px-4 py-2 rounded-lg text-label-md hover:bg-surface-container-highest transition-colors active:scale-95"
                    onClick={allSelected ? deselectAll : selectAll}
                  >
                    {allSelected ? 'Deselect all' : 'Select all'}
                  </button>
                  <select
                    className="px-3 py-2 bg-surface-container-low border border-outline-variant rounded-lg text-label-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                    value={queuePipeline}
                    onChange={e => setQueuePipeline(e.target.value)}
                    disabled={selected.size === 0}
                  >
                    {HISTORY_PIPELINE_PRESETS.map(p => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                  <button
                    className="bg-primary text-on-primary px-4 py-2 rounded-lg text-label-md font-semibold hover:opacity-90 active:scale-95 disabled:opacity-40 transition-all"
                    disabled={selected.size === 0}
                    onClick={handleBulkQueue}
                  >
                    Queue ({selected.size})
                  </button>
                  <button
                    className="border border-error text-error px-4 py-2 rounded-lg text-label-md hover:bg-error hover:text-on-error active:scale-95 disabled:opacity-40 transition-all"
                    disabled={selected.size === 0 || deleting}
                    onClick={handleBulkDelete}
                  >
                    {deleting ? 'Deleting…' : `Delete (${selected.size})`}
                  </button>
                  <button
                    className="bg-surface-container-high text-secondary px-4 py-2 rounded-lg text-label-md hover:bg-surface-container-highest transition-colors active:scale-95"
                    onClick={toggleSelectMode}
                  >
                    Cancel
                  </button>
                </>
              ) : (
                items.length > 0 && (
                  <button
                    className="bg-surface-container-high text-secondary px-4 py-2 rounded-lg text-label-md hover:bg-surface-container-highest transition-colors active:scale-95"
                    onClick={toggleSelectMode}
                  >
                    Select
                  </button>
                )
              )}
            </div>
          </div>

          <div className="flex flex-col md:flex-row gap-4 items-center">
            <div className="relative flex-1 group">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant group-focus-within:text-primary transition-colors" style={{ fontSize: '18px' }}>search</span>
              <input
                className="w-full bg-surface-container-low border border-outline-variant rounded-lg pl-10 pr-4 py-2.5 focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-body-md outline-none"
                type="search"
                placeholder="Search by title or channel…"
                value={searchInput}
                onChange={e => handleSearchChange(e.target.value)}
              />
            </div>
            <button
              className={`flex items-center gap-2 border px-5 py-2.5 rounded-lg text-label-md transition-colors flex-shrink-0 ${
                favoritesOnly
                  ? 'border-primary bg-primary-container text-on-primary-container'
                  : 'border-outline-variant text-secondary hover:bg-surface-container-low'
              }`}
              onClick={toggleFavoritesFilter}
            >
              <span className="material-symbols-outlined" style={{ fontSize: '18px', fontVariationSettings: favoritesOnly ? "'FILL' 1" : "'FILL' 0" }}>star</span>
              Favorites
            </button>
          </div>
        </div>

        {/* Queue success message */}
        {queueMsg && (
          <div className="mx-6 mt-4 bg-tertiary-fixed text-on-tertiary-container rounded-lg px-4 py-3 text-body-sm">
            {queueMsg} — <Link to="/queue" className="underline underline-offset-2">View queue →</Link>
          </div>
        )}

        {/* History list */}
        {items.length === 0 ? (
          <div className="p-12 text-center text-secondary text-body-md">No videos processed yet.</div>
        ) : (
          <div className="divide-y divide-outline-variant">
            {items.map(item => {
              const type = classifyVideo(item.char_count, item.has_chapters)
              const isSelected = selected.has(item.video_id)
              return (
                <div
                  key={item.video_id}
                  className={`p-4 md:px-6 md:py-5 flex items-center gap-4 hover:bg-surface-container-low transition-colors group cursor-pointer ${isSelected ? 'bg-primary-container/30' : ''}`}
                  onClick={() => selectMode ? toggleItem(item.video_id) : navigate(`/result/${item.video_id}`)}
                >
                  {/* Star / checkbox */}
                  {selectMode ? (
                    <input
                      type="checkbox"
                      className="w-4 h-4 accent-primary flex-shrink-0"
                      checked={isSelected}
                      onChange={() => toggleItem(item.video_id)}
                      onClick={e => e.stopPropagation()}
                    />
                  ) : (
                    <button
                      className={`material-symbols-outlined flex-shrink-0 transition-colors ${item.is_favorite ? 'text-amber-400' : 'text-secondary/40 hover:text-amber-400'}`}
                      style={{ fontSize: '20px', fontVariationSettings: item.is_favorite ? "'FILL' 1" : "'FILL' 0", background: 'none', border: 'none', cursor: 'pointer' }}
                      onClick={e => handleToggleFavorite(e, item.video_id)}
                      title={item.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
                    >star</button>
                  )}

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <h3 className="text-body-md text-on-surface font-semibold truncate mb-0.5">{item.title ?? 'Untitled'}</h3>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-on-surface-variant text-body-sm">
                      {item.author && <span>{item.author}</span>}
                      {item.author && <span className="w-1 h-1 rounded-full bg-outline-variant flex-shrink-0" />}
                      <span>{new Date(item.created_at).toLocaleDateString('ru-RU')}</span>
                      {item.char_count && (
                        <>
                          <span className="w-1 h-1 rounded-full bg-outline-variant flex-shrink-0" />
                          <span>{item.char_count.toLocaleString()} chars</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Right-side badges */}
                  <div className="flex items-center gap-3 flex-shrink-0">
                    {/* Stage checks */}
                    <div className="flex gap-0.5 text-tertiary">
                      <span
                        className={`material-symbols-outlined ${item.has_cleaned ? 'text-tertiary' : 'text-surface-container-highest'}`}
                        style={{ fontSize: '18px' }}
                        title={item.has_cleaned ? 'AI Cleanup: done' : 'AI Cleanup: not run'}
                      >check_circle</span>
                      <span
                        className={`material-symbols-outlined ${item.has_summary ? 'text-tertiary' : 'text-surface-container-highest'}`}
                        style={{ fontSize: '18px' }}
                        title={item.has_summary ? 'Summary: done' : 'Summary: not run'}
                      >check_circle</span>
                    </div>

                    {/* Type badge */}
                    {type && (
                      <span className={`px-2 py-0.5 rounded text-label-sm flex items-center gap-1 ${typeBadgeClass(type.key)}`} title={`Auto-mode: ${type.mode}`}>
                        <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>{typeIcon(type.key)}</span>
                        {type.label}
                      </span>
                    )}

                    {/* Language badge */}
                    {item.language && (
                      <span className="bg-surface-container-high text-on-surface-variant px-2 py-0.5 rounded text-label-sm">
                        {item.language.toUpperCase()}
                      </span>
                    )}

                    {/* Delete button — appears on hover */}
                    {!selectMode && (
                      <button
                        className="opacity-0 group-hover:opacity-100 transition-opacity border border-error text-error px-3 py-1 rounded text-label-sm hover:bg-error hover:text-on-error active:scale-95"
                        onClick={e => { e.stopPropagation(); handleDelete(item.video_id) }}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Load more / pagination */}
        {hasMore && (
          <div className="p-6 bg-surface-container-low/50 flex justify-center">
            <button
              className="text-primary text-label-md hover:underline decoration-2 underline-offset-4"
              onClick={() => load(page + 1)}
            >
              Show More
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
