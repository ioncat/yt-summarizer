import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getResult, deleteResult, startCleanup, ResultResponse } from '../api'

type Tab = 'subtitles' | 'cleaned'

function formatDuration(seconds: number | null): string {
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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  function loadResult(switchTab = false) {
    if (!videoId) return
    getResult(videoId)
      .then(data => {
        setResult(data)
        if (switchTab) setActiveTab(data.cleanup_status === 'done' ? 'cleaned' : 'subtitles')
        if (data.cleanup_status !== 'processing') stopPolling()
      })
      .catch(() => setError('Could not load result'))
  }

  // Initial load
  useEffect(() => {
    loadResult(true)
    return stopPolling
  }, [videoId])

  // Start polling if we land on a page already being cleaned
  useEffect(() => {
    if (result?.cleanup_status === 'processing' && !pollRef.current) {
      pollRef.current = setInterval(() => loadResult(true), 3000)
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

  async function handleDelete() {
    if (!videoId) return
    await deleteResult(videoId)
    navigate('/history')
  }

  async function handleCleanup() {
    if (!videoId || !result) return
    try {
      setCleanupError('')
      await startCleanup(videoId)
      setResult({ ...result, cleanup_status: 'processing', cleaned_text: null })
      pollRef.current = setInterval(() => loadResult(true), 3000)
    } catch {
      setCleanupError('Could not reach the backend. Make sure it is running on port 8000.')
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
          {result.char_count && <div className="meta-item">Characters: <span>{result.char_count.toLocaleString()}</span></div>}
          <div className="meta-item">Saved: <span>{formatDate(result.created_at)}</span></div>
        </div>
        <div className="actions">
          <button className="btn btn-secondary" onClick={handleCopy}>
            {copied ? 'Copied!' : 'Copy text'}
          </button>
          <button
            className="btn btn-ai"
            onClick={handleCleanup}
            disabled={result.cleanup_status === 'processing'}
          >
            {result.cleanup_status === 'processing'
              ? <><span className="btn-spinner" /> Cleaning…</>
              : result.cleanup_status === 'done'
                ? '↺ Re-run AI cleanup'
                : '✦ Clean with AI'}
          </button>
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
            className={`result-tab ${activeTab === 'cleaned' ? 'active' : ''} ${!result.cleanup_status || result.cleanup_status === 'failed' ? 'tab-unavailable' : ''}`}
            onClick={() => result.cleanup_status === 'done' && setActiveTab('cleaned')}
          >
            {result.cleanup_status === 'processing'
              ? <><span className="tab-spinner" />Cleaning…</>
              : 'Cleaned'}
          </button>
        </div>
        <div className="formatted-text">{displayText}</div>
      </div>
    </div>
  )
}
