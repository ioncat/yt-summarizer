import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getResult, deleteResult, ResultResponse } from '../api'

function formatDuration(seconds: number | null): string {
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function ResultPage() {
  const { videoId } = useParams<{ videoId: string }>()
  const navigate = useNavigate()
  const [result, setResult] = useState<ResultResponse | null>(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!videoId) return
    getResult(videoId)
      .then(setResult)
      .catch(() => setError('Could not load result'))
  }, [videoId])

  async function handleCopy() {
    if (!result?.formatted_text) return
    await navigator.clipboard.writeText(result.formatted_text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  async function handleDelete() {
    if (!videoId) return
    await deleteResult(videoId)
    navigate('/history')
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
        </div>
        <div className="actions">
          <button className="btn btn-secondary" onClick={handleCopy}>
            {copied ? 'Copied!' : 'Copy text'}
          </button>
          <button className="btn btn-danger" onClick={handleDelete}>Delete</button>
          <a className="btn btn-secondary" href={result.url} target="_blank" rel="noreferrer">
            Open video
          </a>
        </div>
        <div className="formatted-text">{result.formatted_text}</div>
      </div>
    </div>
  )
}
