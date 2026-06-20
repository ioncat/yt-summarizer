import { useEffect, useState, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { getHistory, deleteResult, deleteResultsBulk, queueBulkAdd, toggleFavorite, HistoryItem } from '../api'
import { classifyVideo, VideoType } from '../utils/videoType'

const HISTORY_PIPELINE_PRESETS = [
  { value: 'cleanup', label: 'Cleanup', stages: ['cleanup'] },
  { value: 'summary', label: 'Summary', stages: ['summary'] },
  { value: 'cleanup_summary', label: 'Cleanup + Summary', stages: ['cleanup', 'summary'] },
]

function TypeBadge({ type }: { type: VideoType }) {
  const configs: Record<string, { icon: string; bg: string; text: string }> = {
    short:           { icon: 'description', bg: 'bg-surface-container-high', text: 'text-on-surface-variant' },
    long:            { icon: 'article',     bg: 'bg-surface-container-high', text: 'text-on-surface-variant' },
    long_structured: { icon: 'article',     bg: 'bg-secondary-container',    text: 'text-on-secondary-container' },
    xl:              { icon: 'menu_book',   bg: 'bg-error-container',         text: 'text-on-error-container' },
  }
  const c = configs[type.key] ?? configs.short
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded ${c.bg} ${c.text} text-tag-uppercase font-bold tracking-wider uppercase`}>
      <span className="material-symbols-outlined text-[14px]">{c.icon}</span>
      {type.label}
    </span>
  )
}

export default function HistoryPage() {
  const [items, setItems]             = useState<HistoryItem[]>([])
  const [page, setPage]               = useState(1)
  const [hasMore, setHasMore]         = useState(false)
  const [error, setError]             = useState('')
  const [selectMode, setSelectMode]   = useState(false)
  const [selected, setSelected]       = useState<Set<string>>(new Set())
  const [deleting, setDeleting]       = useState(false)
  const [queuePipeline, setQueuePipeline] = useState('cleanup_summary')
  const [queueMsg, setQueueMsg]       = useState<string | null>(null)
  const [search, setSearch]           = useState('')
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

  function selectAll()   { setSelected(new Set(items.map(i => i.video_id))) }
  function deselectAll() { setSelected(new Set()) }

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
    const urls = items
      .filter(i => selected.has(i.video_id))
      .map(i => `https://www.youtube.com/watch?v=${i.video_id}`)
    try {
      const res = await queueBulkAdd(urls, stages, true)
      setQueueMsg(`Added ${res.added} video${res.added !== 1 ? 's' : ''} to queue`)
      setSelected(new Set())
      setSelectMode(false)
    } catch {
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
    <div className="p-8 max-w-[1200px] mx-auto">
      <div className="bg-error-container rounded-xl p-6 text-on-error-container">{error}</div>
    </div>
  )

  const allSelected = items.length > 0 && selected.size === items.length

  const inputBase = 'bg-surface-container-low border border-outline-variant rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-body-md text-on-surface'

  return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto">
      <div className="bg-surface-container-lowest rounded-xl shadow-sm border border-outline-variant overflow-hidden">

        {/* Header */}
        <div className="p-6 border-b border-outline-variant space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="text-headline-xl font-bold text-on-surface">History</h2>
            {!selectMode && items.length > 0 && (
              <button
                onClick={toggleSelectMode}
                className="bg-surface-container-high text-secondary px-4 py-2 rounded-lg text-label-md font-medium hover:bg-surface-container-highest transition-colors active:scale-[0.98]"
              >
                Select
              </button>
            )}
            {selectMode && (
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={allSelected ? deselectAll : selectAll}
                  className="text-label-sm text-secondary hover:text-on-surface transition-colors px-3 py-1.5 rounded-lg hover:bg-surface-container-high"
                >
                  {allSelected ? 'Deselect all' : 'Select all'}
                </button>
                <select
                  value={queuePipeline}
                  onChange={e => setQueuePipeline(e.target.value)}
                  disabled={selected.size === 0}
                  className={`${inputBase} px-3 py-1.5 text-label-md appearance-none text-sm disabled:opacity-50`}
                >
                  {HISTORY_PIPELINE_PRESETS.map(p => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
                <button
                  onClick={handleBulkQueue}
                  disabled={selected.size === 0}
                  className="bg-primary text-on-primary px-3 py-1.5 rounded-lg text-label-sm font-bold hover:opacity-90 active:scale-[0.98] disabled:opacity-50"
                >
                  Queue ({selected.size})
                </button>
                <button
                  onClick={handleBulkDelete}
                  disabled={selected.size === 0 || deleting}
                  className="border border-error text-error px-3 py-1.5 rounded-lg text-label-sm font-medium hover:bg-error hover:text-on-error active:scale-[0.98] disabled:opacity-50 transition-colors"
                >
                  {deleting ? 'Deleting…' : `Delete (${selected.size})`}
                </button>
                <button
                  onClick={toggleSelectMode}
                  className="text-label-sm text-secondary hover:text-on-surface transition-colors px-3 py-1.5 rounded-lg hover:bg-surface-container-high"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>

          {/* Search + Favorites */}
          <div className="flex flex-col md:flex-row gap-3 items-center">
            <div className="relative flex-1 group w-full">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-[20px] group-focus-within:text-primary transition-colors">
                search
              </span>
              <input
                type="search"
                className={`${inputBase} w-full pl-10 pr-4 py-2.5`}
                placeholder="Search by title or channel..."
                value={searchInput}
                onChange={e => handleSearchChange(e.target.value)}
              />
            </div>
            <button
              onClick={toggleFavoritesFilter}
              className={`flex items-center gap-2 border px-5 py-2.5 rounded-lg text-label-md font-medium transition-colors flex-shrink-0 ${
                favoritesOnly
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-outline-variant text-secondary hover:bg-surface-container-low'
              }`}
            >
              <span
                className="material-symbols-outlined text-[20px]"
                style={{ fontVariationSettings: favoritesOnly ? "'FILL' 1" : "'FILL' 0" }}
              >
                grade
              </span>
              Favorites
            </button>
          </div>

          {/* Queue message */}
          {queueMsg && (
            <div className="flex items-center gap-2 bg-tertiary-container/20 border border-tertiary/30 rounded-lg px-4 py-3">
              <span className="material-symbols-outlined text-tertiary text-[18px]">check_circle</span>
              <span className="text-body-sm text-on-surface">
                {queueMsg} — <Link to="/queue" className="font-semibold text-primary underline">View queue →</Link>
              </span>
            </div>
          )}
        </div>

        {/* List */}
        {items.length === 0 ? (
          <div className="py-16 text-center text-secondary text-body-md">
            No videos processed yet.
          </div>
        ) : (
          <div className="divide-y divide-outline-variant">
            {items.map(item => {
              const type = classifyVideo(item.char_count, item.has_chapters)
              const isSelected = selected.has(item.video_id)
              const date = new Date(item.created_at).toLocaleDateString('ru-RU', {
                day: '2-digit', month: '2-digit', year: 'numeric'
              })

              return (
                <div
                  key={item.video_id}
                  className={`group flex items-center gap-4 px-4 md:px-6 py-4 md:py-5 hover:bg-surface-container-low transition-colors cursor-pointer ${isSelected ? 'bg-surface-container-low' : ''}`}
                  onClick={() => selectMode ? toggleItem(item.video_id) : navigate(`/result/${item.video_id}`)}
                >
                  {/* Select checkbox */}
                  {selectMode && (
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleItem(item.video_id)}
                      onClick={e => e.stopPropagation()}
                      className="w-4 h-4 rounded accent-primary flex-shrink-0"
                    />
                  )}

                  {/* Star */}
                  {!selectMode && (
                    <button
                      onClick={e => handleToggleFavorite(e, item.video_id)}
                      title={item.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
                      className="material-symbols-outlined text-[22px] transition-colors flex-shrink-0 focus:outline-none"
                      style={{
                        fontVariationSettings: item.is_favorite ? "'FILL' 1" : "'FILL' 0",
                        color: item.is_favorite ? '#f59e0b' : undefined,
                      }}
                      aria-label={item.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
                    >
                      star
                    </button>
                  )}

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <h3 className="text-body-md font-semibold text-on-surface truncate mb-0.5">
                      {item.title ?? 'Untitled'}
                    </h3>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-on-surface-variant text-body-sm">
                      {item.author && <span>{item.author}</span>}
                      {item.author && <span className="w-1 h-1 rounded-full bg-outline-variant" />}
                      <span>{date}</span>
                      {item.char_count != null && (
                        <>
                          <span className="w-1 h-1 rounded-full bg-outline-variant" />
                          <span>{item.char_count.toLocaleString()} chars</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Stage checks */}
                  <div className="flex gap-0.5 text-tertiary flex-shrink-0">
                    <span
                      className={`material-symbols-outlined text-[18px] ${item.has_cleaned ? 'text-tertiary' : 'text-outline-variant'}`}
                      title={item.has_cleaned ? 'AI Cleanup: done' : 'AI Cleanup: not run'}
                    >
                      check_circle
                    </span>
                    <span
                      className={`material-symbols-outlined text-[18px] ${item.has_summary ? 'text-tertiary' : 'text-outline-variant'}`}
                      title={item.has_summary ? 'Summary: done' : 'Summary: not run'}
                    >
                      check_circle
                    </span>
                  </div>

                  {/* Type badge */}
                  {type && <TypeBadge type={type} />}

                  {/* Language badge */}
                  {item.language && (
                    <span className="bg-surface-container-high px-2 py-0.5 rounded text-tag-uppercase font-bold tracking-wider text-on-surface-variant flex-shrink-0">
                      {item.language.toUpperCase()}
                    </span>
                  )}

                  {/* Delete (hover reveal) */}
                  {!selectMode && (
                    <button
                      onClick={e => { e.stopPropagation(); handleDelete(item.video_id) }}
                      className="opacity-0 group-hover:opacity-100 transition-opacity border border-error text-error px-3 py-1 rounded text-label-sm font-medium hover:bg-error hover:text-on-error active:scale-[0.98] flex-shrink-0"
                    >
                      Delete
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* Show More */}
        {hasMore && (
          <div className="p-6 bg-surface-container-low/50 flex justify-center border-t border-outline-variant">
            <button
              onClick={() => load(page + 1)}
              className="text-primary text-label-md font-medium hover:underline decoration-2 underline-offset-4"
            >
              Show More Activity
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
