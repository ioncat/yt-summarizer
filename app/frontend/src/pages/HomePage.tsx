import { useState, useEffect, FormEvent } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { processVideo, getSettings, getHealth, AllSettings, queueBulkAdd, VideoAlreadyExistsError } from '../api'

const LANGUAGES = [
  { value: 'auto', label: 'Auto-detect' },
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
  const [pipeline, setPipeline] = useState('extract')
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

  function extractUrlFromLine(line: string): string {
    const match = line.match(/https?:\/\/[^\s|"'<>]+/)
    if (!match) return line.trim()
    return match[0].replace(/[,;.:!?]+$/, '')
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
      // Use selected pipeline preset stages
      const preset = PIPELINE_PRESETS.find(p => p.value === pipeline)
      const stages = preset?.stages ?? ['extract']

      if (stages.length > 1) {
        // Multi-stage → queue
        setLoading(true)
        try {
          const res = await queueBulkAdd([trimmedUrl], stages)
          if (res.duplicates?.length) {
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
        // Extract only → direct flow
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
      if (res.added > 0) setBulkText('')
    } catch (err) {
      setBulkError(err instanceof Error ? err.message : 'Failed to add to queue')
    } finally {
      setBulkLoading(false)
    }
  }

  const inputBase = 'w-full px-4 py-3 bg-surface-container-low border border-outline-variant rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-body-md text-on-surface'
  const selectBase = inputBase + ' appearance-none cursor-pointer'

  return (
    <div className="flex-grow flex flex-col items-center justify-start p-6 md:p-12 max-w-[1200px] mx-auto w-full gap-8 pt-8">

      {/* Missing config warning */}
      {missingConfig.length > 0 && (
        <div className="w-full max-w-2xl bg-error-container border border-error/30 rounded-xl px-5 py-3 flex items-center gap-3">
          <span className="material-symbols-outlined text-error text-[20px]">warning</span>
          <span className="text-body-sm text-on-error-container">
            Required settings missing: <strong>{missingConfig.join(', ')}</strong>.{' '}
            <Link to="/settings" className="font-semibold underline">Go to Settings →</Link>
          </span>
        </div>
      )}

      {/* Main form card */}
      <div className="w-full max-w-2xl bg-surface-container-lowest border border-outline-variant rounded-xl p-8 shadow-sm">
        <div className="text-center mb-10">
          <h2 className="text-headline-xl font-bold text-on-surface mb-2">YT Summarizer</h2>
          <p className="text-body-md text-secondary">Paste a YouTube URL to extract and format subtitles.</p>
        </div>

        <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
          {/* URL input */}
          <div className="flex flex-col gap-2">
            <label className="text-label-md text-on-surface-variant font-medium" htmlFor="url">
              YouTube URL
            </label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 material-symbols-outlined text-secondary text-[20px]">
                link
              </span>
              <input
                id="url"
                type="text"
                className={inputBase + ' pl-12'}
                placeholder="https://www.youtube.com/watch?v=..."
                value={url}
                onChange={e => setUrl(e.target.value)}
                required
                autoFocus
              />
            </div>
          </div>

          {/* Language + Pipeline row */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <label className="text-label-md text-on-surface-variant font-medium" htmlFor="lang">
                Subtitle language
              </label>
              <select
                id="lang"
                className={selectBase}
                value={language}
                onChange={e => setLanguage(e.target.value)}
              >
                {LANGUAGES.map(l => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-2">
              <label className="text-label-md text-on-surface-variant font-medium" htmlFor="pipeline">
                Pipeline
              </label>
              <select
                id="pipeline"
                className={selectBase}
                value={pipeline}
                onChange={e => setPipeline(e.target.value)}
                disabled={autoPipeline}
              >
                {PIPELINE_PRESETS.map(p => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Auto-pipeline checkbox */}
          <div className="flex items-center gap-3 pt-1">
            <input
              id="auto-pipeline"
              type="checkbox"
              className="w-5 h-5 rounded border-outline-variant cursor-pointer accent-primary"
              checked={autoPipeline}
              disabled={!ollamaOnline}
              onChange={e => {
                setAutoPipeline(e.target.checked)
                localStorage.setItem('yt_summarizer_auto_pipeline', String(e.target.checked))
              }}
            />
            <label
              htmlFor="auto-pipeline"
              className={`text-label-md text-on-surface cursor-pointer ${!ollamaOnline ? 'opacity-50' : ''}`}
            >
              Run full pipeline (Transcript + Cleanup + Summary)
              {!ollamaOnline && <span className="ml-2 text-secondary font-normal">— Ollama offline</span>}
            </label>
          </div>

          {/* Error */}
          {error && (
            <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3">
              <p className="text-body-sm text-on-error-container whitespace-pre-line">{error}</p>
            </div>
          )}

          {/* Action buttons */}
          <div className="flex flex-col md:flex-row gap-4 pt-4">
            <button
              type="submit"
              disabled={loading || !url.trim()}
              className="flex-grow bg-primary text-on-primary py-4 px-6 rounded-lg text-label-md font-bold transition-all hover:opacity-90 active:scale-[0.98] shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Submitting…' : 'Add to queue'}
            </button>
            <button
              type="button"
              onClick={() => { setBulkOpen(o => !o); setBulkResult(null); setBulkError('') }}
              className="flex-grow bg-surface-container-high text-on-surface-variant py-4 px-6 rounded-lg text-label-md font-medium transition-all hover:bg-surface-container-highest active:scale-[0.98]"
            >
              {bulkOpen ? '✕ Cancel bulk' : 'Bulk add'}
            </button>
          </div>
        </form>
      </div>

      {/* Bulk Add panel */}
      {bulkOpen && (
        <div className="w-full max-w-2xl bg-surface-container-lowest border border-outline-variant rounded-xl p-8 shadow-sm">
          <h3 className="text-headline-lg font-semibold text-on-surface mb-6">Bulk Add to Queue</h3>
          <form className="flex flex-col gap-4" onSubmit={handleBulkSubmit}>
            <div className="flex flex-col gap-2">
              <label className="text-label-md text-on-surface-variant font-medium">
                URLs <span className="text-secondary font-normal">(one per line)</span>
              </label>
              <textarea
                className="w-full px-4 py-3 bg-surface-container-low border border-outline-variant rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-body-sm text-on-surface resize-y font-mono"
                placeholder={'https://www.youtube.com/watch?v=...\nhttps://youtu.be/...'}
                value={bulkText}
                onChange={e => { setBulkText(e.target.value); setBulkResult(null) }}
                rows={5}
              />
              {bulkCount > 0 && (
                <span className="text-label-sm text-secondary">{bulkCount} URL{bulkCount !== 1 ? 's' : ''} detected</span>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <label className="text-label-md text-on-surface-variant font-medium" htmlFor="bulk-pipeline">
                Pipeline
              </label>
              <select
                id="bulk-pipeline"
                className={selectBase}
                value={bulkPipeline}
                onChange={e => setBulkPipeline(e.target.value)}
              >
                {PIPELINE_PRESETS.map(p => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>

            {bulkError && (
              <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3">
                <p className="text-body-sm text-on-error-container">{bulkError}</p>
              </div>
            )}

            {bulkResult && (() => {
              const skipped = [
                ...bulkResult.duplicates.map(u => ({ url: u, reason: 'duplicate' })),
                ...bulkResult.invalid.map(u => ({ url: u, reason: 'invalid' })),
              ]
              return (
                <div className="flex flex-col gap-2">
                  {bulkResult.added > 0 && (
                    <div className="bg-tertiary-container/20 border border-tertiary/30 rounded-lg px-4 py-3 flex items-center gap-2">
                      <span className="material-symbols-outlined text-tertiary text-[18px]">check_circle</span>
                      <span className="text-body-sm text-on-surface">
                        Added <strong>{bulkResult.added}</strong> to queue.{' '}
                        <Link to="/queue" className="font-semibold text-primary underline">View queue →</Link>
                      </span>
                    </div>
                  )}
                  {skipped.length > 0 && (
                    <div className="bg-surface-container-high border border-outline-variant rounded-lg px-4 py-3">
                      <p className="text-label-sm text-secondary mb-2">Skipped: {skipped.length}</p>
                      <ul className="flex flex-col gap-1">
                        {skipped.map(({ url, reason }, i) => (
                          <li key={i} className="flex items-baseline gap-2 text-body-sm">
                            <span className="font-mono text-on-surface-variant break-all opacity-80">{url}</span>
                            <span className="text-secondary italic flex-shrink-0">{reason}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )
            })()}

            <button
              type="submit"
              disabled={bulkLoading || bulkCount === 0}
              className="bg-primary text-on-primary py-4 px-6 rounded-lg text-label-md font-bold transition-all hover:opacity-90 active:scale-[0.98] shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {bulkLoading ? 'Adding…' : `Add to queue (${bulkCount} URL${bulkCount !== 1 ? 's' : ''})`}
            </button>
          </form>
        </div>
      )}
    </div>
  )
}
