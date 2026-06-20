import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { getStatus, getResult, processVideo, startCleanup, startSummary, cancelCleanup, cancelSummary } from '../api'

const LANG_LABELS: Record<string, string> = {
  ru: 'Russian', en: 'English', uk: 'Ukrainian',
}

type Stage = 'extracting' | 'cleaning' | 'summarizing'

const STAGES: { id: Stage; label: string; icon: string }[] = [
  { id: 'extracting',  label: 'Extracting subtitles', icon: 'closed_caption' },
  { id: 'cleaning',    label: 'Cleaning with AI',     icon: 'auto_awesome'   },
  { id: 'summarizing', label: 'Summarizing',           icon: 'summarize'      },
]

function StageIcon({ status }: { status: 'active' | 'done' | 'pending' }) {
  if (status === 'done') {
    return (
      <span
        className="material-symbols-outlined text-[22px] text-tertiary"
        style={{ fontVariationSettings: "'FILL' 1" }}
      >
        check_circle
      </span>
    )
  }
  if (status === 'active') {
    return (
      <span className="material-symbols-outlined text-[22px] text-primary pulse-dot">
        pending
      </span>
    )
  }
  return (
    <span className="material-symbols-outlined text-[22px] text-outline-variant">
      radio_button_unchecked
    </span>
  )
}

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
                  setStage('summarizing')
                  try {
                    await startSummary(videoId)
                    cleanupIntervalRef.current = setInterval(async () => {
                      try {
                        const r = await getResult(videoId)
                        if (r.summary_status !== 'processing') {
                          clearInterval(cleanupIntervalRef.current!)
                          cleanupIntervalRef.current = null
                          navigate(`/result/${videoId}`)
                        }
                      } catch (err) {
                        console.error('[Processing] summary poll failed:', err)
                        clearInterval(cleanupIntervalRef.current!)
                        cleanupIntervalRef.current = null
                        navigate(`/result/${videoId}`)
                      }
                    }, 3000)
                  } catch (err) {
                    console.error('[Processing] startSummary failed:', err)
                    setError(err instanceof Error ? err.message : 'Summarization failed to start')
                  }
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
  }, [taskId, videoId, navigate, autoPipeline]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleStopPipeline() {
    if (!videoId) return
    if (cleanupIntervalRef.current) {
      clearInterval(cleanupIntervalRef.current)
      cleanupIntervalRef.current = null
    }
    try {
      if (stage === 'cleaning')    await cancelCleanup(videoId)
      if (stage === 'summarizing') await cancelSummary(videoId)
    } catch (err) {
      console.error('[Processing] stopPipeline cancel failed:', err)
    }
    navigate(`/result/${videoId}`)
  }

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

  const stageOrder: Stage[] = ['extracting', 'cleaning', 'summarizing']
  const currentIdx = stageOrder.indexOf(stage)

  function stageStatus(id: Stage): 'active' | 'done' | 'pending' {
    const idx = stageOrder.indexOf(id)
    if (idx < currentIdx) return 'done'
    if (idx === currentIdx) return 'active'
    return 'pending'
  }

  const statusText = stage === 'cleaning'
    ? 'AI cleanup running…'
    : stage === 'summarizing'
    ? 'Summarizing…'
    : 'This usually takes 15–30 seconds'

  return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto flex items-start justify-center">
      <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm w-full max-w-md mt-12">

        {/* Header */}
        <div className="px-8 pt-8 pb-6 border-b border-outline-variant">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-[28px]">
              {error ? 'error' : 'hourglass_top'}
            </span>
            <h2 className="text-headline-lg font-bold text-on-surface">
              {error ? 'Processing Failed' : 'Processing'}
            </h2>
          </div>
        </div>

        {/* Body */}
        <div className="px-8 py-8 space-y-6">

          {!error ? (
            <>
              {autoPipeline ? (
                /* Pipeline stepper */
                <div className="space-y-0">
                  {STAGES.map((s, i) => {
                    const status = stageStatus(s.id)
                    return (
                      <div key={s.id} className="flex items-start gap-4">
                        {/* Icon + connector */}
                        <div className="flex flex-col items-center">
                          <StageIcon status={status} />
                          {i < STAGES.length - 1 && (
                            <div className={`w-0.5 h-8 mt-1 ${
                              stageOrder.indexOf(s.id) < currentIdx
                                ? 'bg-tertiary'
                                : 'bg-outline-variant'
                            }`} />
                          )}
                        </div>

                        {/* Label */}
                        <div className="pb-8 pt-0.5">
                          <p className={`text-body-md font-semibold ${
                            status === 'active'  ? 'text-primary'
                            : status === 'done'  ? 'text-tertiary'
                            : 'text-on-surface-variant opacity-50'
                          }`}>
                            {s.label}
                          </p>
                          {status === 'active' && (
                            <p className="text-body-sm text-secondary mt-0.5">{statusText}</p>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                /* Single-stage spinner */
                <div className="flex flex-col items-center gap-4 py-6">
                  <span className="material-symbols-outlined text-[48px] text-primary pulse-dot">
                    pending
                  </span>
                  <p className="text-body-md font-semibold text-on-surface">Extracting subtitles…</p>
                  <p className="text-body-sm text-secondary">{statusText}</p>
                </div>
              )}

              {/* Stop button */}
              {autoPipeline && (stage === 'cleaning' || stage === 'summarizing') && (
                <div className="pt-2">
                  <button
                    onClick={handleStopPipeline}
                    className="w-full py-2.5 border border-outline-variant text-on-surface-variant text-label-md rounded-lg hover:border-error hover:text-error transition-colors active:scale-[0.98] flex items-center justify-center gap-2"
                  >
                    <span className="material-symbols-outlined text-[18px]">stop_circle</span>
                    Stop pipeline
                  </button>
                </div>
              )}
            </>
          ) : (
            /* Error state */
            <>
              <div className="flex items-start gap-3 p-4 bg-error-container/20 border border-error/30 rounded-lg">
                <span className="material-symbols-outlined text-error text-[18px] flex-shrink-0 mt-0.5">warning</span>
                <p className="text-body-sm text-on-error-container">{error}</p>
              </div>

              {availableLangs.length > 0 && (
                <div className="space-y-3">
                  <p className="text-body-sm text-secondary">Try one of the available languages:</p>
                  <div className="flex flex-wrap gap-2">
                    {availableLangs.map(lang => (
                      <button
                        key={lang}
                        disabled={retrying}
                        onClick={() => retryWithLang(lang)}
                        className="px-4 py-2 bg-surface-container-high text-on-surface text-label-md rounded-lg hover:bg-surface-dim transition-colors active:scale-[0.98] disabled:opacity-50"
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
