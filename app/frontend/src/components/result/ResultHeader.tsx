import { toggleFavorite, ResultResponse } from '../../api'
import { Setter, formatDuration, formatDate } from './helpers'

interface ResultHeaderProps {
  result: ResultResponse
  videoId: string | undefined
  setResult: Setter<ResultResponse | null>
  displayCharCount: number | null
  charCountOf: string   // which text the number counts: the number changes with the tab, so the label says whose it is (NS-17 item 3)
}

export function ResultHeader({ result, videoId, setResult, displayCharCount, charCountOf }: ResultHeaderProps) {
  return (
          <div className="p-6 border-b border-outline-variant">
            <div className="flex justify-between items-start mb-4 gap-3">
              <h2 className="text-headline-xl font-bold text-on-surface flex-1 leading-tight">
                {result.title ?? 'Untitled'}
              </h2>
              <button
                onClick={async () => {
                  const r = await toggleFavorite(videoId!)
                  setResult(prev => prev ? { ...prev, is_favorite: r.is_favorite } : prev)
                }}
                title={result.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
                className="material-symbols-outlined text-[28px] transition-colors flex-shrink-0 focus:outline-none"
                style={{
                  fontVariationSettings: result.is_favorite ? "'FILL' 1" : "'FILL' 0",
                  color: result.is_favorite ? '#f59e0b' : undefined,
                }}
              >star</button>
            </div>

            {/* Meta row */}
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-secondary text-body-sm">
              {result.author && (
                <div><span className="font-semibold text-on-surface">Channel:</span> {result.author}</div>
              )}
              <div><span className="font-semibold text-on-surface">Duration:</span> {formatDuration(result.duration)}</div>
              {result.language && (
                <div><span className="font-semibold text-on-surface">Language:</span> {result.language.toUpperCase()}</div>
              )}
              {displayCharCount != null && (
                <div><span className="font-semibold text-on-surface">Characters ({charCountOf}):</span> {displayCharCount.toLocaleString()}</div>
              )}
              <div><span className="font-semibold text-on-surface">Saved:</span> {formatDate(result.created_at)}</div>
            </div>
          </div>
  )
}
