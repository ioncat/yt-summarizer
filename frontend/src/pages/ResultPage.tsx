import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getResult, deleteResult, startCleanup, cancelCleanup, getSettings, getModels, saveSettings, ResultResponse } from '../api'

type Tab = 'subtitles' | 'cleaned'

function formatDuration(seconds: number | null): string {
  if (seconds === 0) return '0:00'
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}


function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function ResultPage() {
  const { videoId } = useParams<{ videoId: string }>()
  const navigate = useNavigate()
  const [result, setResult] = useState<ResultResponse | null>(null)
  const [error, setError] = useState('')
  const [cleanupError, setCleanupError] = useState('')
  const [copied, setCopied] = useState(false)
  const [activeTab, setActiveTab] = useState<Tab>('subtitles')
  const [model, setModel] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [cleanupElapsedSeconds, setCleanupElapsedSeconds] = useState<number | null>(null)
  const [localCleanupDurationSeconds, setLocalCleanupDurationSeconds] = useState<number | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cleanupElapsedRef = useRef<number | null>(null)
  const prevCleanupStatusRef = useRef<string | null | undefined>(undefined)
  // Preserve existing prompts so model-only save doesn't overwrite them
  const cleanupPromptsRef = useRef<{ system_prompt: string | null; user_prompt_template: string | null }>({
    system_prompt: null, user_prompt_template: null,
  })

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  function stopCleanupTimer() {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
  }

  function startCleanupTimer() {
    stopCleanupTimer()
    const startedAt = Date.now()
    setCleanupElapsedSeconds(0)
    cleanupElapsedRef.current = 0
    timerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000)
      cleanupElapsedRef.current = elapsed
      setCleanupElapsedSeconds(elapsed)
    }, 1000)
  }

  function loadResult(switchTab = false) {
    if (!videoId) return
    getResult(videoId)
      .then(data => {
        const prevStatus = prevCleanupStatusRef.current
        prevCleanupStatusRef.current = data.cleanup_status
        setResult(data)
        if (switchTab) {
          setActiveTab(data.cleanup_status === 'done' ? 'cleaned' : 'subtitles')
        } else if (prevStatus === 'processing' && data.cleanup_status === 'done') {
          // Auto-switch only on transition processing → done
          setActiveTab('cleaned')
        }
        if (data.cleanup_status !== 'processing') {
          if (prevStatus === 'processing' && data.cleanup_status === 'done' && data.cleanup_duration_seconds == null) {
            setLocalCleanupDurationSeconds(cleanupElapsedRef.current)
          } else if (data.cleanup_duration_seconds != null) {
            setLocalCleanupDurationSeconds(null)
          }
          stopPolling()
          stopCleanupTimer()
          setCleanupElapsedSeconds(null)
        } else if (!timerRef.current) {
          startCleanupTimer()
        }
      })
      .catch(err => { console.error('[Result] getResult failed:', err); setError('Could not load result') })
  }

  // Initial load
  useEffect(() => {
    loadResult(true)
    return () => {
      stopPolling()
      stopCleanupTimer()
    }
  }, [videoId])

  // Load model list and current model once
  useEffect(() => {
    Promise.all([getSettings(), getModels()])
      .then(([s, list]) => {
        setModel(s.cleanup.model ?? '')
        setModels(list)
        cleanupPromptsRef.current = {
          system_prompt: s.cleanup.system_prompt ?? null,
          user_prompt_template: s.cleanup.user_prompt_template ?? null,
        }
      })
      .catch(err => console.error('[Result] failed to load model settings:', err))
  }, [])

  // Start polling if we land on a page already being cleaned
  useEffect(() => {
    if (result?.cleanup_status === 'processing' && !pollRef.current) {
      pollRef.current = setInterval(() => loadResult(false), 3000)
    }
  }, [result?.cleanup_status])

  const displayText = (activeTab === 'cleaned' && result?.cleaned_text)
    ? result.cleaned_text
    : result?.formatted_text

  async function handleCopy() {
    if (!displayText) return
    await navigator.clipboard.writeText(displayText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  async function handleCancel() {
    if (!videoId) return
    stopPolling()
    stopCleanupTimer()
    try {
      await cancelCleanup(videoId)
    } catch (err) {
      console.error('[Result] cancelCleanup failed:', err)
    }
    setCleanupElapsedSeconds(null)
    cleanupElapsedRef.current = null
    setLocalCleanupDurationSeconds(null)
    setResult(prev => prev ? { ...prev, cleanup_status: null, cleaned_text: null, cleanup_duration_seconds: null } : prev)
  }

  async function handleDelete() {
    if (!videoId) return
    if (!window.confirm('Delete this video and all its data? This cannot be undone.')) return
    try {
      await deleteResult(videoId)
      navigate('/history')
    } catch (err) {
      console.error('[Result] deleteResult failed:', err)
    }
  }

  async function handleModelChange(newModel: string) {
    setModel(newModel)
    try {
      await saveSettings('cleanup', {
        system_prompt: cleanupPromptsRef.current.system_prompt,
        user_prompt_template: cleanupPromptsRef.current.user_prompt_template,
        model: newModel || null,
      })
    } catch (err) {
      console.error('[Result] saveSettings model failed:', err)
    }
  }

  async function handleCleanup() {
    if (!videoId || !result) return
    try {
      setCleanupError('')
      await startCleanup(videoId)
      setLocalCleanupDurationSeconds(null)
      prevCleanupStatusRef.current = 'processing'
      startCleanupTimer()
      setResult({ ...result, cleanup_status: 'processing', cleaned_text: null, cleanup_duration_seconds: null })
      stopPolling()
      pollRef.current = setInterval(() => loadResult(false), 3000)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      console.error('[Cleanup] failed:', err)
      setCleanupError(msg)
    }
  }

  if (error) return (
    <div className="container">
      <div className="card"><div className="error-box">{error}</div></div>
    </div>
  )

  if (!result) return (
    <div className="container">
      <div className="card"><div className="status-box"><div className="spinner" /></div></div>
    </div>
  )

  return (
    <div className="container">
      <div className="card">
        <h2>{result.title ?? 'Untitled'}</h2>
        <div className="meta">
          {result.author && <div className="meta-item">Channel: <span>{result.author}</span></div>}
          <div className="meta-item">Duration: <span>{formatDuration(result.duration)}</span></div>
          {result.language && <div className="meta-item">Language: <span>{result.language.toUpperCase()}</span></div>}
          {(() => {
            const subtitlesCount = result.char_count ?? result.formatted_text?.length ?? null
            const cleanedCount = result.cleaned_text?.length ?? null
            const displayCount = activeTab === 'cleaned' ? cleanedCount : subtitlesCount
            return (subtitlesCount != null || cleanedCount != null) ? (
              <div className="meta-item">Characters: <span>
                {displayCount != null ? displayCount.toLocaleString() : '—'}
              </span></div>
            ) : null
          })()}
          {result.cleanup_status === 'processing' && cleanupElapsedSeconds != null ? (
            <div className="meta-item">Cleaning: <span>{formatDuration(cleanupElapsedSeconds)}</span></div>
          ) : (result.cleanup_duration_seconds ?? localCleanupDurationSeconds) != null && (
            <div className="meta-item">Cleaned in: <span>{formatDuration(result.cleanup_duration_seconds ?? localCleanupDurationSeconds)}</span></div>
          )}
          <div className="meta-item">Saved: <span>{formatDate(result.created_at)}</span></div>
        </div>
        <div className="actions">
          <button className="btn btn-secondary" onClick={handleCopy}>
            {copied ? 'Copied!' : 'Copy text'}
          </button>
          <select
            className="model-select-inline"
            value={model}
            onChange={e => handleModelChange(e.target.value)}
            disabled={models.length === 0}
            title={models.length === 0 ? 'Ollama offline — cannot load models' : 'AI model for cleanup'}
          >
            <option value="">— model —</option>
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          {result.cleanup_status === 'processing' ? (
            <button className="btn btn-secondary" onClick={handleCancel}>
              ✕ Stop
            </button>
          ) : (
            <button className="btn btn-ai" onClick={handleCleanup}>
              {result.cleanup_status === 'done' ? '↺ Re-run AI cleanup' : '✦ Clean with AI'}
            </button>
          )}
          <button className="btn btn-danger" onClick={handleDelete}>Delete</button>
          <a className="btn btn-secondary" href={result.url} target="_blank" rel="noreferrer">
            Open video
          </a>
        </div>
        {(result.cleanup_status === 'failed' || cleanupError) && (
          <div className="cleanup-error">
            {cleanupError || 'Ollama unavailable — make sure it is running and try again.'}
          </div>
        )}
        <div className="result-tabs">
          <button
            className={`result-tab ${activeTab === 'subtitles' ? 'active' : ''}`}
            onClick={() => setActiveTab('subtitles')}
          >
            Subtitles
          </button>
          <button
            className={`result-tab ${activeTab === 'cleaned' ? 'active' : ''}`}
            onClick={() => setActiveTab('cleaned')}
          >
            {result.cleanup_status === 'processing'
              ? <><span className="tab-spinner" />Cleaning…</>
              : 'Cleaned'}
          </button>
        </div>
        {activeTab === 'cleaned' && !result.cleaned_text ? (
          <div className="empty">
            {result.cleanup_status === 'processing'
              ? 'AI cleanup is running…'
              : result.cleanup_status === 'failed'
                ? 'Cleanup failed. Click "↺ Re-run AI cleanup" to try again.'
                : 'No cleaned version yet. Click "✦ Clean with AI" above to start.'}
          </div>
        ) : (
          <div className="formatted-text">
            {displayText}
          </div>
        )}
      </div>
    </div>
  )
}
