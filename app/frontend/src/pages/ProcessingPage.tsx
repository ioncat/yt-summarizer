import { useEffect, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { getStatus, processVideo, stopFileTranscription } from '../api'

const LANG_LABELS: Record<string, string> = {
  ru: 'Russian', en: 'English', uk: 'Ukrainian',
}

// Extraction only: cleanup, summary and mind map are queue items now (NS-11), followed on the Result and Queue pages.
export default function ProcessingPage() {
  const { taskId, videoId } = useParams<{ taskId: string; videoId: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [progressText, setProgressText] = useState<string | null>(null)
  const [availableLangs, setAvailableLangs] = useState<string[]>([])
  const [retrying, setRetrying] = useState(false)
  const [stopping, setStopping] = useState(false)

  const originalUrl = searchParams.get('url') ?? ''

  useEffect(() => {
    if (!taskId) return

    const interval = setInterval(async () => {
      try {
        const res = await getStatus(taskId)
        if (res.progress_text) setProgressText(res.progress_text)
        if (res.status === 'completed') {
          setProgressText(null)
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
  }, [taskId, videoId, navigate]) // eslint-disable-line react-hooks/exhaustive-deps

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

  // An uploaded file (its id starts with "file-") is a queue item: it may wait its turn, and it can be stopped (NS-11 stage 5)
  const isFile = (videoId ?? '').startsWith('file-')
  async function stopTranscription() {
    if (!videoId) return
    setStopping(true)
    try {
      await stopFileTranscription(videoId)   // the next status poll shows "Transcription stopped"
    } catch (err) {
      console.error('[Processing] stop failed:', err)
      setStopping(false)
    }
  }

  const isTranscribing = isFile || progressText != null && (
    progressText.startsWith('segment') || progressText.startsWith('transcribing')
  )
  const statusText = progressText ?? 'This usually takes 15–30 seconds'

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
            <div className="flex flex-col items-center gap-4 py-6">
              <span className="material-symbols-outlined text-[48px] text-primary pulse-dot">
                pending
              </span>
              <p className="text-body-md font-semibold text-on-surface">
                {isTranscribing ? 'Transcribing…' : 'Extracting subtitles…'}
              </p>
              <p className="text-body-sm text-secondary">{statusText}</p>
              {isFile && (
                <button
                  onClick={stopTranscription}
                  disabled={stopping}
                  title="Stop this transcription: nothing is saved"
                  className="px-4 py-2 border border-error text-error rounded-lg text-label-md font-semibold hover:bg-error-container transition-colors disabled:opacity-50"
                >
                  {stopping ? 'Stopping…' : 'Stop'}
                </button>
              )}
            </div>
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
