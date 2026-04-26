import { useState, useEffect, FormEvent } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { processVideo, getSettings } from '../api'

const LANGUAGES = [
  { value: 'ru', label: 'Russian' },
  { value: 'en', label: 'English' },
  { value: 'uk', label: 'Ukrainian' },
]

export default function HomePage() {
  const [url, setUrl] = useState('')
  const [language, setLanguage] = useState('ru')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [missingConfig, setMissingConfig] = useState<string[]>([])
  const navigate = useNavigate()

  useEffect(() => {
    getSettings().then(s => {
      const missing: string[] = []
      if (!s.app.ytdlp_path) missing.push('yt-dlp path')
      if (!s.app.cookies_path) missing.push('Cookies')
      setMissingConfig(missing)
    }).catch(err => { console.error('[Home] getSettings failed:', err) })
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await processVideo(url.trim(), language)
      navigate(`/processing/${res.task_id}/${res.video_id}?url=${encodeURIComponent(url.trim())}`)
    } catch (err) {
      console.error('[Home] processVideo failed:', err)
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
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
            <p className="field-hint">Select the language of the video's subtitles. If unavailable, we'll show which languages are.</p>
          </div>
          {error && <div className="error-box" style={{ marginBottom: '1rem' }}>{error}</div>}
          <button className="btn btn-primary" type="submit" disabled={loading || !url.trim()}>
            {loading ? 'Submitting…' : 'Extract subtitles'}
          </button>
        </form>
      </div>
    </div>
  )
}
