import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getResult, deleteResult,
  startCleanup, cancelCleanup,
  startSummary, cancelSummary,
  getSettings, getModels, saveSettings,
  ResultResponse,
} from '../api'

type Tab = 'subtitles' | 'cleaned' | 'summary'

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
  const [summaryError, setSummaryError] = useState('')
  const [copied, setCopied] = useState(false)
  const [activeTab, setActiveTab] = useState<Tab>('subtitles')
  const [cleanupModel, setCleanupModel] = useState('')
  const [summaryModel, setSummaryModel] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [cleanupElapsedSeconds, setCleanupElapsedSeconds] = useState<number | null>(null)
  const [summaryElapsedSeconds, setSummaryElapsedSeconds] = useState<number | null>(null)
  const [localCleanupDuration, setLocalCleanupDuration] = useState<number | null>(null)
  const [localSummaryDuration, setLocalSummaryDuration] = useState<number | null>(null)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const summaryPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cleanupTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const summaryTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cleanupElapsedRef = useRef<number | null>(null)
  const summaryElapsedRef = useRef<number | null>(null)
  const prevCleanupStatusRef = useRef<string | null | undefined>(undefined)
  const prevSummaryStatusRef = useRef<string | null | undefined>(undefined)
  const cleanupPromptsRef = useRef<{ system_prompt: string | null; user_prompt_template: string | null }>({
    system_prompt: null, user_prompt_template: null,
  })
  const summaryPromptsRef = useRef<{ system_prompt: string | null; user_prompt_template: string | null }>({
    system_prompt: null, user_prompt_template: null,
  })

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }
  function stopSummaryPolling() {
    if (summaryPollRef.current) { clearInterval(summaryPollRef.current); summaryPollRef.current = null }
  }
  function stopCleanupTimer() {
    if (cleanupTimerRef.current) { clearInterval(cleanupTimerRef.current); cleanupTimerRef.current = null }
  }
  function stopSummaryTimer() {
    if (summaryTimerRef.current) { clearInterval(summaryTimerRef.current); summaryTimerRef.current = null }
  }
  function startCleanupTimer() {
    stopCleanupTimer()
    const startedAt = Date.now()
    setCleanupElapsedSeconds(0)
    cleanupElapsedRef.current = 0
    cleanupTimerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000)
      cleanupElapsedRef.current = elapsed
      setCleanupElapsedSeconds(elapsed)
    }, 1000)
  }
  function startSummaryTimer() {
    stopSummaryTimer()
    const startedAt = Date.now()
    setSummaryElapsedSeconds(0)
    summaryElapsedRef.current = 0
    summaryTimerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000)
      summaryElapsedRef.current = elapsed
      setSummaryElapsedSeconds(elapsed)
    }, 1000)
  }

  function loadResult(switchTab = false) {
    if (!videoId) return
    getResult(videoId)
      .then(data => {
        const prevCleanup = prevCleanupStatusRef.current
        const prevSummary = prevSummaryStatusRef.current
        prevCleanupStatusRef.current = data.cleanup_status
        prevSummaryStatusRef.current = data.summary_status
        setResult(data)

        // Tab auto-switching on initial load
        if (switchTab) {
          if (data.summary_status === 'done') setActiveTab('summary')
          else if (data.cleanup_status === 'done') setActiveTab('cleaned')
          else setActiveTab('subtitles')
        } else {
          if (prevCleanup === 'processing' && data.cleanup_status === 'done') setActiveTab('cleaned')
          if (prevSummary === 'processing' && data.summary_status === 'done') setActiveTab('summary')
        }

        // Cleanup polling/timer management
        if (data.cleanup_status !== 'processing') {
          if (prevCleanup === 'processing' && data.cleanup_status === 'done' && data.cleanup_duration_seconds == null) {
            setLocalCleanupDuration(cleanupElapsedRef.current)
          } else if (data.cleanup_duration_seconds != null) {
            setLocalCleanupDuration(null)
          }
          stopPolling()
          stopCleanupTimer()
          setCleanupElapsedSeconds(null)
        } else if (!cleanupTimerRef.current) {
          startCleanupTimer()
        }

        // Summary polling/timer management
        if (data.summary_status !== 'processing') {
          if (prevSummary === 'processing' && data.summary_status === 'done' && data.summary_duration_seconds == null) {
            setLocalSummaryDuration(summaryElapsedRef.current)
          } else if (data.summary_duration_seconds != null) {
            setLocalSummaryDuration(null)
          }
          stopSummaryPolling()
          stopSummaryTimer()
          setSummaryElapsedSeconds(null)
        } else if (!summaryTimerRef.current) {
          startSummaryTimer()
        }
      })
      .catch(err => { console.error('[Result] getResult failed:', err); setError('Could not load result') })
  }

  useEffect(() => {
    loadResult(true)
    return () => {
      stopPolling()
      stopSummaryPolling()
      stopCleanupTimer()
      stopSummaryTimer()
    }
  }, [videoId])

  useEffect(() => {
    Promise.all([getSettings(), getModels()])
      .then(([s, list]) => {
        setCleanupModel(s.cleanup.model ?? '')
        setSummaryModel(s.summarization.model ?? '')
        setModels(list)
        cleanupPromptsRef.current = {
          system_prompt: s.cleanup.system_prompt ?? null,
          user_prompt_template: s.cleanup.user_prompt_template ?? null,
        }
        summaryPromptsRef.current = {
          system_prompt: s.summarization.system_prompt ?? null,
          user_prompt_template: s.summarization.user_prompt_template ?? null,
        }
      })
      .catch(err => console.error('[Result] failed to load model settings:', err))
  }, [])

  useEffect(() => {
    if (result?.cleanup_status === 'processing' && !pollRef.current) {
      pollRef.current = setInterval(() => loadResult(false), 3000)
    }
  }, [result?.cleanup_status])

  useEffect(() => {
    if (result?.summary_status === 'processing' && !summaryPollRef.current) {
      summaryPollRef.current = setInterval(() => loadResult(false), 3000)
    }
  }, [result?.summary_status])

  const displayText =
    activeTab === 'summary' ? result?.summary_text :
    activeTab === 'cleaned' ? (result?.cleaned_text ?? result?.formatted_text) :
    result?.formatted_text

  async function handleCopy() {
    if (!displayText) return
    await navigator.clipboard.writeText(displayText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  async function handleCancelCleanup() {
    if (!videoId) return
    stopPolling(); stopCleanupTimer()
    try { await cancelCleanup(videoId) }
    catch (err) { console.error('[Result] cancelCleanup failed:', err) }
    setCleanupElapsedSeconds(null); cleanupElapsedRef.current = null; setLocalCleanupDuration(null)
    setResult(prev => prev ? { ...prev, cleanup_status: null, cleaned_text: null, cleanup_duration_seconds: null } : prev)
  }

  async function handleCancelSummary() {
    if (!videoId) return
    stopSummaryPolling(); stopSummaryTimer()
    try { await cancelSummary(videoId) }
    catch (err) { console.error('[Result] cancelSummary failed:', err) }
    setSummaryElapsedSeconds(null); summaryElapsedRef.current = null; setLocalSummaryDuration(null)
    setResult(prev => prev ? { ...prev, summary_status: null, summary_text: null, summary_duration_seconds: null } : prev)
  }

  async function handleDelete() {
    if (!videoId) return
    if (!window.confirm('Delete this video and all its data? This cannot be undone.')) return
    try { await deleteResult(videoId); navigate('/history') }
    catch (err) { console.error('[Result] deleteResult failed:', err) }
  }

  async function handleCleanupModelChange(newModel: string) {
    setCleanupModel(newModel)
    try {
      await saveSettings('cleanup', {
        system_prompt: cleanupPromptsRef.current.system_prompt,
        user_prompt_template: cleanupPromptsRef.current.user_prompt_template,
        model: newModel || null,
      })
    } catch (err) { console.error('[Result] saveSettings cleanup model failed:', err) }
  }

  async function handleSummaryModelChange(newModel: string) {
    setSummaryModel(newModel)
    try {
      await saveSettings('summarization', {
        system_prompt: summaryPromptsRef.current.system_prompt,
        user_prompt_template: summaryPromptsRef.current.user_prompt_template,
        model: newModel || null,
      })
    } catch (err) { console.error('[Result] saveSettings summary model failed:', err) }
  }

  async function handleCleanup() {
    if (!videoId || !result) return
    try {
      setCleanupError('')
      await startCleanup(videoId)
      setLocalCleanupDuration(null)
      prevCleanupStatusRef.current = 'processing'
      startCleanupTimer()
      setResult({ ...result, cleanup_status: 'processing', cleanup_duration_seconds: null })
      stopPolling()
      pollRef.current = setInterval(() => loadResult(false), 3000)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      console.error('[Cleanup] failed:', err)
      setCleanupError(msg)
    }
  }

  async function handleSummarize() {
    if (!videoId || !result) return
    try {
      setSummaryError('')
      await startSummary(videoId)
      setLocalSummaryDuration(null)
      prevSummaryStatusRef.current = 'processing'
      startSummaryTimer()
      setResult({ ...result, summary_status: 'processing', summary_duration_seconds: null })
      stopSummaryPolling()
      summaryPollRef.current = setInterval(() => loadResult(false), 3000)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      console.error('[Summary] failed:', err)
      setSummaryError(msg)
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

  const cleanupDuration = result.cleanup_duration_seconds ?? localCleanupDuration
  const summaryDuration = result.summary_duration_seconds ?? localSummaryDuration

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
            const summaryCount = result.summary_text?.length ?? null
            const displayCount =
              activeTab === 'summary' ? summaryCount :
              activeTab === 'cleaned' ? cleanedCount :
              subtitlesCount
            return (subtitlesCount != null || cleanedCount != null || summaryCount != null) ? (
              <div className="meta-item">Characters: <span>
                {displayCount != null ? displayCount.toLocaleString() : '—'}
              </span></div>
            ) : null
          })()}
          {activeTab === 'cleaned' && (
            result.cleanup_status === 'processing' && cleanupElapsedSeconds != null ? (
              <div className="meta-item">
                Cleaning: <span>{formatDuration(cleanupElapsedSeconds)}</span>
                {result.cleanup_paragraphs_done != null && result.cleanup_paragraphs_total != null && (
                  <span className="meta-model"> · paragraph {result.cleanup_paragraphs_done} / {result.cleanup_paragraphs_total}</span>
                )}
              </div>
            ) : cleanupDuration != null ? (
              <div className="meta-item">
                Cleaned in: <span>{formatDuration(cleanupDuration)}</span>
                {result.cleanup_model && <span className="meta-model"> · {result.cleanup_model}</span>}
              </div>
            ) : null
          )}
          {activeTab === 'summary' && (
            result.summary_status === 'processing' && summaryElapsedSeconds != null ? (
              <div className="meta-item">
                Summarizing: <span>{formatDuration(summaryElapsedSeconds)}</span>
                {result.summary_chunks_done != null && result.summary_chunks_total != null && (
                  <span className="meta-model"> · chunk {result.summary_chunks_done} / {result.summary_chunks_total}</span>
                )}
              </div>
            ) : summaryDuration != null ? (
              <div className="meta-item">
                Summarized in: <span>{formatDuration(summaryDuration)}</span>
                {result.summary_model && <span className="meta-model"> · {result.summary_model}</span>}
                {result.summary_mode === 'map_reduce' && result.summary_chunks_count != null && (
                  <span className="meta-model"> · {result.summary_chunks_count} chunks</span>
                )}
              </div>
            ) : null
          )}
          <div className="meta-item">Saved: <span>{formatDate(result.created_at)}</span></div>
        </div>

        <div className="actions">
          <button className="btn btn-secondary" onClick={handleCopy}>
            {copied ? 'Copied!' : 'Copy text'}
          </button>

          {activeTab === 'cleaned' && (<>
            <select
              className="model-select-inline"
              value={cleanupModel}
              onChange={e => handleCleanupModelChange(e.target.value)}
              disabled={models.length === 0}
              title={models.length === 0 ? 'Ollama offline — cannot load models' : 'Model for AI cleanup'}
            >
              <option value="">— cleanup model —</option>
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            {result.cleanup_status === 'processing' ? (
              <button className="btn btn-secondary" onClick={handleCancelCleanup}>✕ Stop</button>
            ) : (
              <button className="btn btn-ai" onClick={handleCleanup}>
                {result.cleanup_status === 'done' ? '↺ Re-run AI cleanup' : '✦ Clean with AI'}
              </button>
            )}
          </>)}

          {activeTab === 'summary' && (<>
            <select
              className="model-select-inline"
              value={summaryModel}
              onChange={e => handleSummaryModelChange(e.target.value)}
              disabled={models.length === 0}
              title={models.length === 0 ? 'Ollama offline — cannot load models' : 'Model for summarization'}
            >
              <option value="">— summary model —</option>
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            {result.summary_status === 'processing' ? (
              <button className="btn btn-secondary" onClick={handleCancelSummary}>✕ Stop</button>
            ) : (
              <button className="btn btn-ai" onClick={handleSummarize}>
                {result.summary_status === 'done' ? '↺ Re-run summary' : '✦ Summarize'}
              </button>
            )}
          </>)}

          <a className="btn btn-secondary" href={result.url} target="_blank" rel="noreferrer">
            Open video
          </a>
          <button className="btn btn-danger" onClick={handleDelete}>Delete</button>
        </div>

        {activeTab === 'cleaned' && (result.cleanup_status === 'failed' || cleanupError) && (
          <div className="cleanup-error">
            {cleanupError || 'Cleanup failed — make sure Ollama is running and a model is selected.'}
          </div>
        )}
        {activeTab === 'summary' && (result.summary_status === 'failed' || summaryError) && (
          <div className="cleanup-error">
            {summaryError || 'Summarization failed — make sure Ollama is running and a model is selected.'}
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
          <button
            className={`result-tab ${activeTab === 'summary' ? 'active' : ''}`}
            onClick={() => setActiveTab('summary')}
          >
            {result.summary_status === 'processing'
              ? <><span className="tab-spinner" />Summarizing…</>
              : 'Summary'}
          </button>
        </div>

        {activeTab === 'summary' ? (
          <>
            {!result.summary_text ? (
              <div className="empty">
                {result.summary_status === 'processing'
                  ? 'Summarization is running…'
                  : result.summary_status === 'failed'
                    ? 'Summary failed. Click "↺ Re-run summary" to try again.'
                    : 'No summary yet. Click "✦ Summarize" above to generate one.'}
              </div>
            ) : (
              <div className="formatted-text">{result.summary_text}</div>
            )}
          </>
        ) : activeTab === 'cleaned' && !result.cleaned_text ? (
          <div className="empty">
            {result.cleanup_status === 'processing'
              ? 'AI cleanup is running…'
              : result.cleanup_status === 'failed'
                ? 'Cleanup failed. Click "↺ Re-run AI cleanup" to try again.'
                : 'No cleaned version yet. Click "✦ Clean with AI" above to start.'}
          </div>
        ) : (
          <div className="formatted-text">{displayText}</div>
        )}
      </div>
    </div>
  )
}
