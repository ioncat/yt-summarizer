import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { getStatus, getResult, processVideo, startCleanup } from '../api'

const LANG_LABELS: Record<string, string> = {
  ru: 'Russian', en: 'English', uk: 'Ukrainian',
}

type Stage = 'extracting' | 'cleaning'

export default function ProcessingPage() {
  const { taskId, videoId } = useParams<{ taskId: string; videoId: string }>()
  const [searchParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [stage, setStage] = useState<Stage>('extracting')
  const [error, setError] = useState('')
  const [availableLangs, setAvailableLangs] = useState<string[]>([])
  const [retrying, setRetrying] = useState(false)
  const cleanupIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const autoPipeline = (location.state as { autoPipeline?: boolean } | null)?.autoPipeline ?? false
  const originalUrl = searchParams.get('url') ?? ''

  useEffect(() => {
    if (!taskId) return

    const interval = setInterval(async () => {
      try {
        const res = await getStatus(taskId)
        if (res.status === 'completed') {
          clearInterval(interval)
          if (autoPipeline && videoId) {
            setStage('cleaning')
            try {
              await startCleanup(videoId)
            } catch (err) {
              console.error('[Processing] startCleanup failed:', err)
              navigate(`/result/${videoId}`)
              return
            }
            cleanupIntervalRef.current = setInterval(async () => {
              try {
                const result = await getResult(videoId)
                if (result.cleanup_status !== 'processing') {
                  clearInterval(cleanupIntervalRef.current!)
                  cleanupIntervalRef.current = null
                  navigate(`/result/${videoId}`)
                }
              } catch (err) {
                console.error('[Processing] cleanup poll failed:', err)
                clearInterval(cleanupIntervalRef.current!)
                cleanupIntervalRef.current = null
                navigate(`/result/${videoId}`)
              }
            }, 3000)
          } else {
            navigate(`/result/${videoId}`)
          }
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

    return () => {
      clearInterval(interval)
      if (cleanupIntervalRef.current) clearInterval(cleanupIntervalRef.current)
    }
  }, [taskId, videoId, navigate, autoPipeline])

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
          {!error ? (
            <>
              {autoPipeline ? (
                <div className="pipeline-stages">
                  <div className={`pipeline-stage ${stage === 'extracting' ? 'active' : 'done'}`}>
                    <span className="stage-icon">{stage === 'extracting' ? <span className="tab-spinner" /> : '✓'}</span>
                    <span>Extracting subtitles</span>
                  </div>
                  <div className={`pipeline-stage ${stage === 'cleaning' ? 'active' : stage === 'extracting' ? 'pending' : 'done'}`}>
                    <span className="stage-icon">{stage === 'cleaning' ? <span className="tab-spinner" /> : stage === 'extracting' ? '②' : '✓'}</span>
                    <span>Cleaning with AI</span>
                  </div>
                  {/* TODO Phase 2: add stage 'summarizing' here when Epic 15 (LLM Summarization) ships */}
                </div>
              ) : (
                <>
                  <div className="spinner" />
                  <p style={{ fontSize: '1.1rem', fontWeight: 600 }}>Extracting subtitles…</p>
                </>
              )}
              <p style={{ color: '#888', marginTop: '1rem', fontSize: '0.9rem' }}>
                {stage === 'cleaning' ? 'AI cleanup running…' : 'This usually takes 15–30 seconds'}
              </p>
            </>
          ) : (
            <>
              <div className="error-box" style={{ marginBottom: '1rem' }}>{error}</div>
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
