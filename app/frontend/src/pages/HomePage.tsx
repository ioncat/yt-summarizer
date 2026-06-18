import { useState, useEffect, FormEvent } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { processVideo, getSettings, getHealth, AllSettings, queueBulkAdd, VideoAlreadyExistsError } from '../api'

const LANGUAGES = [
  { value: 'auto', label: 'Auto (detect)' },
  { value: 'ru', label: 'Russian' },
  { value: 'en', label: 'English' },
  { value: 'uk', label: 'Ukrainian' },
]

const PIPELINE_PRESETS = [
  { value: 'extract', label: 'Extract only', stages: ['extract'] },
  { value: 'cleanup', label: 'Extract + Cleanup', stages: ['extract', 'cleanup'] },
  { value: 'full', label: 'Full pipeline', stages: ['extract', 'cleanup', 'summary'] },
]

export default function HomePage() {
  const [url, setUrl] = useState('')
  const [language, setLanguage] = useState('auto')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [missingConfig, setMissingConfig] = useState<string[]>([])
  const [allSettings, setAllSettings] = useState<AllSettings | null>(null)
  const [autoPipeline, setAutoPipeline] = useState(
    () => localStorage.getItem('yt_summarizer_auto_pipeline') === 'true'
  )
  const [ollamaOnline, setOllamaOnline] = useState(false)

  // Bulk Add panel state
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkText, setBulkText] = useState('')
  const [bulkPipeline, setBulkPipeline] = useState('extract')
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkResult, setBulkResult] = useState<{ added: number; invalid: string[]; duplicates: string[] } | null>(null)
  const [bulkError, setBulkError] = useState('')

  const navigate = useNavigate()

  // Extract URL from each line — handles "URL | title", "title - URL", trailing punctuation, etc.
  function extractUrlFromLine(line: string): string {
    const match = line.match(/https?:\/\/[^\s|"'<>]+/)
    if (!match) return line.trim()
    return match[0].replace(/[,;.:!?]+$/, '')  // strip trailing punctuation, keep slashes
  }

  const bulkUrls = bulkText
    .split('\n')
    .map(l => extractUrlFromLine(l.trim()))
    .filter(l => l.length > 0)
  const bulkCount = bulkUrls.length

  useEffect(() => {
    Promise.all([getSettings(), getHealth()])
      .then(([s, health]) => {
        const missing: string[] = []
        if (!s.app.ytdlp_path) missing.push('yt-dlp path')
        if (!s.app.cookies_path) missing.push('Cookies')
        setMissingConfig(missing)
        setAllSettings(s)
        setOllamaOnline(health.ollama)
      })
      .catch(err => { console.error('[Home] getSettings failed:', err) })
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    const trimmedUrl = url.trim()

    if (autoPipeline) {
      // Full pipeline → always goes through queue for durability
      if (allSettings) {
        const issues: string[] = []
        if (!allSettings.app.ollama_url) issues.push('Ollama URL not configured (Settings → General)')
        if (!allSettings.cleanup.model) issues.push('AI Cleanup model not selected (Settings → AI Cleanup)')
        if (!allSettings.summarization.model) issues.push('Summarization model not selected (Settings → Summarization)')
        if (issues.length) {
          setError('Auto-pipeline is not ready:\n• ' + issues.join('\n• '))
          return
        }
      }
      setLoading(true)
      try {
        const res = await queueBulkAdd([trimmedUrl], ['extract', 'cleanup', 'summary'])
        if (res.duplicates?.length) {
          // Already processed — navigate directly to result
          const vid = res.duplicates[0].replace(/.*[?&]v=/, '').replace(/[&?].*/, '')
          navigate(`/result/${vid}`)
          return
        }
        navigate('/queue')
      } catch (err) {
        console.error('[Home] queueBulkAdd failed:', err)
        setError(err instanceof Error ? err.message : 'Failed to add to queue')
      } finally {
        setLoading(false)
      }
    } else {
      // Extraction only — direct flow (no LLM, no queue needed)
      setLoading(true)
      try {
        const res = await processVideo(trimmedUrl, language)
        navigate(
          `/processing/${res.task_id}/${res.video_id}?url=${encodeURIComponent(trimmedUrl)}`,
          { state: { autoPipeline: false } }
        )
      } catch (err) {
        if (err instanceof VideoAlreadyExistsError) {
          navigate(`/result/${err.videoId}`)
          return
        }
        console.error('[Home] processVideo failed:', err)
        setError(err instanceof Error ? err.message : 'Unknown error')
      } finally {
        setLoading(false)
      }
    }
  }

  async function handleBulkSubmit(e: FormEvent) {
    e.preventDefault()
    if (!bulkCount) return
    setBulkLoading(true)
    setBulkError('')
    setBulkResult(null)
    try {
      const preset = PIPELINE_PRESETS.find(p => p.value === bulkPipeline)
      const stages = preset?.stages ?? ['extract']
      const res = await queueBulkAdd(bulkUrls, stages)
      setBulkResult({ added: res.added, invalid: res.invalid, duplicates: res.duplicates ?? [] })
      if (res.added > 0) {
        setBulkText('')
      }
    } catch (err) {
      setBulkError(err instanceof Error ? err.message : 'Failed to add to queue')
    } finally {
      setBulkLoading(false)
    }
  }

  return (
    <div className="flex flex-col items-center p-6 md:p-12 gap-6 min-h-[calc(100vh-4rem)] justify-center">
      {/* Missing config warning */}
      {missingConfig.length > 0 && (
        <div className="w-full max-w-2xl flex items-center gap-3 bg-error-container text-on-error-container border border-error rounded-xl px-4 py-3 text-label-md">
          <span className="material-symbols-outlined flex-shrink-0" style={{ fontSize: '18px' }}>warning</span>
          <span>Required settings missing: <strong>{missingConfig.join(', ')}</strong>.</span>
          <Link to="/settings" className="ml-auto text-label-sm underline underline-offset-2 hover:no-underline flex-shrink-0">Settings →</Link>
        </div>
      )}

      {/* Main form card */}
      <div className="w-full max-w-2xl bg-surface-container-lowest border border-outline-variant rounded-xl p-8 shadow-sm">
        <div className="text-center mb-10">
          <h2 className="text-headline-xl text-on-surface mb-2">YT Summarizer</h2>
          <p className="text-body-md text-secondary">Paste a YouTube URL to extract and format subtitles.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* URL input with icon */}
          <div className="space-y-2">
            <label className="text-label-md text-on-surface-variant block" htmlFor="url">YouTube URL</label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 material-symbols-outlined text-secondary" style={{ fontSize: '20px' }}>link</span>
              <input
                id="url"
                type="text"
                className="w-full pl-11 pr-4 py-3 bg-surface-container-low border border-outline-variant rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-body-md"
                placeholder="https://www.youtube.com/watch?v=..."
                value={url}
                onChange={e => setUrl(e.target.value)}
                required
                autoFocus
              />
            </div>
          </div>

          {/* Language select */}
          <div className="space-y-2">
            <label className="text-label-md text-on-surface-variant block" htmlFor="lang">Subtitle language</label>
            <select
              id="lang"
              className="w-full px-4 py-3 bg-surface-container-low border border-outline-variant rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-body-md appearance-none cursor-pointer"
              value={language}
              onChange={e => setLanguage(e.target.value)}
            >
              {LANGUAGES.map(l => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
            <p className="text-body-sm text-secondary">Auto detects the video's original language. Override if needed.</p>
          </div>

          {/* Pipeline checkbox */}
          <div className="flex items-center gap-3 pt-2">
            <input
              id="pipeline"
              type="checkbox"
              className="w-5 h-5 text-primary border-outline-variant rounded cursor-pointer focus:ring-primary/20 transition-all accent-primary"
              checked={autoPipeline}
              disabled={!ollamaOnline}
              onChange={e => {
                setAutoPipeline(e.target.checked)
                localStorage.setItem('yt_summarizer_auto_pipeline', String(e.target.checked))
              }}
            />
            <label htmlFor="pipeline" className="text-label-md text-on-surface cursor-pointer select-none">
              Run full pipeline (Extract → Cleanup → Summary)
            </label>
          </div>
          {!ollamaOnline && (
            <p className="text-body-sm text-secondary -mt-2">Ollama offline — full pipeline unavailable.</p>
          )}

          {error && (
            <div className="flex items-start gap-2 bg-error-container text-on-error-container rounded-lg px-4 py-3 text-body-sm whitespace-pre-line">
              <span className="material-symbols-outlined flex-shrink-0 mt-0.5" style={{ fontSize: '16px' }}>error</span>
              {error}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex flex-col md:flex-row gap-4 pt-2">
            <button
              className="flex-1 bg-primary text-on-primary py-4 px-6 rounded-lg text-label-md font-bold transition-all hover:opacity-90 active:scale-95 shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
              type="submit"
              disabled={loading || !url.trim()}
            >
              {loading ? 'Submitting…' : autoPipeline ? 'Add to queue' : 'Extract subtitles'}
            </button>
            <button
              type="button"
              className="flex-1 bg-surface-container-high text-on-surface-variant py-4 px-6 rounded-lg text-label-md font-medium transition-all hover:bg-surface-container-highest active:scale-95"
              onClick={() => { setBulkOpen(o => !o); setBulkResult(null); setBulkError('') }}
            >
              {bulkOpen ? 'Cancel bulk' : 'Bulk add'}
            </button>
          </div>
        </form>
      </div>

      {/* Bulk add panel */}
      {bulkOpen && (
        <div className="w-full max-w-2xl bg-surface-container-lowest border border-outline-variant rounded-xl p-8 shadow-sm">
          <h3 className="text-headline-lg text-on-surface mb-6">Bulk Add to Queue</h3>
          <form onSubmit={handleBulkSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-label-md text-on-surface-variant block">URLs (one per line)</label>
              <textarea
                className="w-full px-4 py-3 bg-surface-container-low border border-outline-variant rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-body-sm resize-y"
                placeholder={"https://www.youtube.com/watch?v=...\nhttps://youtu.be/..."}
                value={bulkText}
                onChange={e => { setBulkText(e.target.value); setBulkResult(null) }}
                rows={6}
              />
            </div>
            <div className="space-y-2">
              <label className="text-label-md text-on-surface-variant block">Pipeline</label>
              <select
                className="w-full px-4 py-3 bg-surface-container-low border border-outline-variant rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-body-md appearance-none cursor-pointer"
                value={bulkPipeline}
                onChange={e => setBulkPipeline(e.target.value)}
              >
                {PIPELINE_PRESETS.map(p => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
            {bulkError && (
              <div className="bg-error-container text-on-error-container rounded-lg px-4 py-3 text-body-sm">{bulkError}</div>
            )}
            {bulkResult && (() => {
              const skipped = [
                ...bulkResult.duplicates.map(u => ({ url: u, reason: 'duplicate' })),
                ...bulkResult.invalid.map(u => ({ url: u, reason: 'invalid' })),
              ]
              const hasAdded = bulkResult.added > 0
              const hasSkipped = skipped.length > 0
              return (
                <div className="space-y-2">
                  {hasAdded && (
                    <div className="bg-tertiary-fixed text-on-tertiary-container rounded-lg px-4 py-3 text-body-sm">
                      ✓ Added to queue: <strong>{bulkResult.added}</strong>.{' '}
                      <Link to="/queue" className="underline underline-offset-2">View queue →</Link>
                    </div>
                  )}
                  {hasSkipped && (
                    <div className="bg-error-container text-on-error-container rounded-lg px-4 py-3 text-body-sm">
                      <div className="font-semibold mb-2">Skipped: {skipped.length}</div>
                      <ul className="space-y-1">
                        {skipped.map(({ url: u, reason }, i) => (
                          <li key={i} className="flex gap-2">
                            <span className="truncate flex-1">{u}</span>
                            <span className="flex-shrink-0 opacity-70">{reason}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {!hasAdded && !hasSkipped && (
                    <div className="bg-surface-container-high text-secondary rounded-lg px-4 py-3 text-body-sm">Nothing added to queue.</div>
                  )}
                </div>
              )
            })()}
            <button
              className="w-full bg-primary text-on-primary py-4 px-6 rounded-lg text-label-md font-bold transition-all hover:opacity-90 active:scale-95 shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
              type="submit"
              disabled={bulkLoading || bulkCount === 0}
            >
              {bulkLoading ? 'Adding…' : `Add to queue (${bulkCount} URL${bulkCount !== 1 ? 's' : ''})`}
            </button>
          </form>
        </div>
      )}
    </div>
  )
}
