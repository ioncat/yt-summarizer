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

    if (autoPipeline && allSettings) {
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
      const res = await processVideo(url.trim(), language)
      navigate(
        `/processing/${res.task_id}/${res.video_id}?url=${encodeURIComponent(url.trim())}`,
        { state: { autoPipeline } }
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
    <div className="container">
      {missingConfig.length > 0 && (
        <div className="settings-warning" style={{ marginBottom: '1rem' }}>
          ⚠ Required settings missing: <strong>{missingConfig.join(', ')}</strong>.{' '}
          <Link to="/settings">Go to Settings →</Link>
        </div>
      )}
      <div className="card">
        <h1>YT Summarizer</h1>
        <p className="subtitle">Paste a YouTube URL to extract and format subtitles.</p>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>YouTube URL</label>
            <input
              type="text"
              placeholder="https://www.youtube.com/watch?v=..."
              value={url}
              onChange={e => setUrl(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="form-group">
            <label>Subtitle language</label>
            <select value={language} onChange={e => setLanguage(e.target.value)}>
              {LANGUAGES.map(l => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
            <p className="field-hint">Auto detects the video's original language. Override if needed.</p>
          </div>
          <div className="form-group">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={autoPipeline}
                disabled={!ollamaOnline}
                onChange={e => {
                  setAutoPipeline(e.target.checked)
                  localStorage.setItem('yt_summarizer_auto_pipeline', String(e.target.checked))
                }}
              />
              Run AI cleanup automatically
            </label>
            <p className="field-hint">
              {ollamaOnline ? 'Runs after extraction. Requires Ollama.' : 'Ollama offline — unavailable.'}
            </p>
          </div>
          {error && <div className="error-box" style={{ marginBottom: '1rem', whiteSpace: 'pre-line' }}>{error}</div>}
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <button className="btn btn-primary" type="submit" disabled={loading || !url.trim()}>
              {loading ? 'Submitting…' : 'Extract subtitles'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => { setBulkOpen(o => !o); setBulkResult(null); setBulkError('') }}
            >
              {bulkOpen ? '✕ Cancel' : '⏱ Bulk add'}
            </button>
          </div>
        </form>
      </div>

      {bulkOpen && (
        <div className="card bulk-panel">
          <h3 style={{ marginTop: 0 }}>Bulk Add to Queue</h3>
          <form onSubmit={handleBulkSubmit}>
            <div className="form-group">
              <label>URLs (one per line)</label>
              <textarea
                className="bulk-textarea"
                placeholder="https://www.youtube.com/watch?v=...&#10;https://youtu.be/..."
                value={bulkText}
                onChange={e => { setBulkText(e.target.value); setBulkResult(null) }}
                rows={6}
              />
            </div>
            <div className="form-group">
              <label>Pipeline</label>
              <select value={bulkPipeline} onChange={e => setBulkPipeline(e.target.value)}>
                {PIPELINE_PRESETS.map(p => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
            {bulkError && <div className="error-box" style={{ marginBottom: '0.75rem' }}>{bulkError}</div>}
            {bulkResult && (() => {
              const skipped = [
                ...bulkResult.duplicates.map(u => ({ url: u, reason: 'duplicate' })),
                ...bulkResult.invalid.map(u => ({ url: u, reason: 'invalid' })),
              ]
              const hasAdded = bulkResult.added > 0
              const hasSkipped = skipped.length > 0
              return (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginBottom: '0.75rem' }}>
                  {hasAdded && (
                    <div className="bulk-result bulk-result--ok">
                      ✓ Added to queue: <strong>{bulkResult.added}</strong>. <Link to="/queue">View queue →</Link>
                    </div>
                  )}
                  {hasSkipped && (
                    <div className="bulk-result bulk-result--err">
                      <div className="bulk-report-line">Skipped: <strong>{skipped.length}</strong></div>
                      <ul className="bulk-skipped-list">
                        {skipped.map(({ url, reason }, i) => (
                          <li key={i}>
                            <span className="bulk-skipped-url">{url}</span>
                            <span className="bulk-skipped-reason">{reason}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {!hasAdded && !hasSkipped && (
                    <div className="bulk-result bulk-result--warn">Nothing added to queue.</div>
                  )}
                </div>
              )
            })()}
            <button
              className="btn btn-primary"
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
