import { useEffect, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { getStatus, processVideo } from '../api'

const STATUS_LABELS: Record<string, string> = {
  pending: 'Starting…',
  processing: 'Extracting subtitles…',
  completed: 'Done!',
  failed: 'Failed',
}

const LANG_LABELS: Record<string, string> = {
  ru: 'Russian', en: 'English', uk: 'Ukrainian',
}

export default function ProcessingPage() {
  const { taskId, videoId } = useParams<{ taskId: string; videoId: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState('pending')
  const [error, setError] = useState('')
  const [availableLangs, setAvailableLangs] = useState<string[]>([])
  const [retrying, setRetrying] = useState(false)

  const originalUrl = searchParams.get('url') ?? ''

  useEffect(() => {
    if (!taskId) return
    const interval = setInterval(async () => {
      try {
        const res = await getStatus(taskId)
        setStatus(res.status)
        if (res.status === 'completed') {
          clearInterval(interval)
          navigate(`/result/${videoId}`)
        } else if (res.status === 'failed') {
          clearInterval(interval)
          setError(res.error_message || 'Processing failed')
          setAvailableLangs(res.available_languages ?? [])
        }
      } catch (err) {
        console.error('[Processing] getStatus failed:', err)
        clearInterval(interval)
        setError('Could not reach the server')
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [taskId, videoId, navigate])

  async function retryWithLang(lang: string) {
    if (!originalUrl) return
    setRetrying(true)
    try {
      const res = await processVideo(originalUrl, lang)
      navigate(`/processing/${res.task_id}/${res.video_id}?url=${encodeURIComponent(originalUrl)}`)
    } catch (err) {
      console.error('[Processing] retryWithLang failed:', err)
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="container">
      <div className="card">
        <div className="status-box">
          {status !== 'failed' ? (
            <>
              <div className="spinner" />
              <p style={{ fontSize: '1.1rem', fontWeight: 600 }}>{STATUS_LABELS[status] ?? status}</p>
              <p style={{ color: '#888', marginTop: '0.5rem', fontSize: '0.9rem' }}>
                This usually takes 15–30 seconds
              </p>
            </>
          ) : (
            <>
              <div className="error-box">{error}</div>
              {availableLangs.length > 0 && (
                <div style={{ marginTop: '1rem' }}>
                  <p style={{ fontSize: '0.9rem', color: '#555', marginBottom: '0.75rem' }}>
                    Try one of the available languages:
                  </p>
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                    {availableLangs.map(lang => (
                      <button
                        key={lang}
                        className="btn btn-secondary"
                        disabled={retrying}
                        onClick={() => retryWithLang(lang)}
                      >
                        {LANG_LABELS[lang] ?? lang.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
