import { useEffect, useRef, useState } from 'react'
import { saveAppSettings, downloadSttModel, getSttModelDownloadStatus, deleteSttModel, AppSettings, SttModelInfo } from '../../api'
import { INPUT, SELECT, Hint, SavedToast } from './primitives'

const STT_DEVICES = [
  { value: 'auto', label: 'Auto (CUDA if available, else CPU)' },
  { value: 'cpu',  label: 'CPU' },
  { value: 'cuda', label: 'GPU (CUDA)' },
]

function fmtSize(mb: number) {
  return mb >= 1000 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`
}

interface SttPanelProps {
  initial: AppSettings
  sttModels: SttModelInfo[]
  onSaved: (s: AppSettings) => void
  onReloadModels: () => void
}

export function SttPanel({ initial, sttModels, onSaved, onReloadModels }: SttPanelProps) {
  const [activeModel, setActiveModel] = useState(initial.stt_model ?? 'base')
  const [device, setDevice]           = useState(initial.stt_device ?? 'auto')
  const [cacheInput, setCacheInput]   = useState(initial.stt_cache_path ?? '')
  const [downloading, setDownloading] = useState<string | null>(null)
  const [progress, setProgress]       = useState<{ downloaded_mb: number; total_mb: number } | null>(null)
  const [speedMbps, setSpeedMbps]     = useState<number | null>(null)
  const [toast, setToast]             = useState('')
  const pollRef    = useRef<ReturnType<typeof setInterval> | null>(null)
  const prevMbRef  = useRef<number>(0)
  const prevTsRef  = useRef<number>(0)

  useEffect(() => {
    setActiveModel(initial.stt_model ?? 'base')
    setDevice(initial.stt_device ?? 'auto')
    setCacheInput(initial.stt_cache_path ?? '')
  }, [initial])

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  async function saveField(patch: Partial<AppSettings>) {
    try {
      const updated = await saveAppSettings(patch)
      onSaved(updated)
      setToast('Saved')
      setTimeout(() => setToast(''), 2000)
    } catch { /* ignore */ }
  }

  async function handleSetActive(name: string) {
    setActiveModel(name)
    await saveField({ stt_model: name })
  }

  async function handleDownload(name: string) {
    setDownloading(name)
    setProgress(null)
    setSpeedMbps(null)
    prevMbRef.current = 0
    prevTsRef.current = Date.now()
    try {
      await downloadSttModel(name)
    } catch {
      setDownloading(null)
      return
    }
    pollRef.current = setInterval(async () => {
      try {
        const s = await getSttModelDownloadStatus(name)
        if (s.status === 'downloading') {
          const now = Date.now()
          const dtSec = (now - prevTsRef.current) / 1000
          const dMb = s.downloaded_mb - prevMbRef.current
          if (dtSec > 0 && dMb > 0) setSpeedMbps(dMb / dtSec)
          prevMbRef.current = s.downloaded_mb
          prevTsRef.current = now
          setProgress({ downloaded_mb: s.downloaded_mb, total_mb: s.total_mb })
        } else if (s.status === 'done' || s.status === 'already_downloaded') {
          clearInterval(pollRef.current!)
          setDownloading(null)
          setProgress(null)
          setSpeedMbps(null)
          onReloadModels()
          await saveField({ stt_model: name })
          setActiveModel(name)
        } else if (s.status === 'failed') {
          clearInterval(pollRef.current!)
          setDownloading(null)
          setProgress(null)
          setSpeedMbps(null)
          alert(`Download failed: ${s.error ?? 'unknown error'}`)
        }
      } catch { /* ignore transient errors */ }
    }, 1500)
  }

  async function handleDelete(name: string) {
    if (!confirm(`Delete model "${name}" from disk?`)) return
    try {
      await deleteSttModel(name)
      onReloadModels()
      if (activeModel === name) {
        setActiveModel('base')
        await saveField({ stt_model: 'base' })
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete')
    }
  }

  return (
    <div className="space-y-6">
      <p className="text-body-sm text-on-surface-variant">
        Speech-to-text engine for transcribing audio when YouTube captions are unavailable.
        Models are downloaded from HuggingFace and cached locally.
      </p>

      {/* Device */}
      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface">Compute device</label>
        <select
          value={device}
          onChange={e => { setDevice(e.target.value); saveField({ stt_device: e.target.value }) }}
          className={SELECT()}
        >
          {STT_DEVICES.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
        </select>
        <Hint>CUDA requires an NVIDIA GPU with CUDA toolkit installed on the host.</Hint>
      </div>

      {/* Cache path */}
      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface">Models cache directory</label>
        <div className="flex gap-2">
          <input
            value={cacheInput}
            onChange={e => setCacheInput(e.target.value)}
            placeholder="Default: ~/.cache/huggingface/hub"
            className={INPUT()}
          />
          <button
            onClick={() => saveField({ stt_cache_path: cacheInput })}
            className="px-4 py-2 bg-primary text-on-primary rounded-lg text-label-md font-semibold hover:bg-primary/90 transition-colors whitespace-nowrap"
          >
            Save
          </button>
        </div>
        <Hint>Leave empty to use the default HuggingFace cache location.</Hint>
      </div>

      {toast && <SavedToast msg={toast} />}

      {/* Model catalog */}
      <div className="space-y-2">
        <p className="text-label-sm text-on-surface-variant uppercase tracking-wider font-bold">Models</p>

        {sttModels.length === 0 && (
          <p className="text-body-sm text-secondary py-4 text-center">Loading models…</p>
        )}

        {[...sttModels].sort((a, b) => {
          const rank = (m: typeof a) => m.name === activeModel ? 0 : m.downloaded ? 1 : 2
          return rank(a) - rank(b)
        }).map(m => {
          const isActive      = m.name === activeModel
          const isDownloading = m.name === downloading
          const langLabel     = m.languages === 1 ? 'EN only' : `${m.languages} languages`

          return (
            <div
              key={m.name}
              className={`border rounded-xl p-4 transition-colors ${
                isActive
                  ? 'border-primary bg-primary/5'
                  : 'border-outline-variant bg-surface-container-lowest'
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                {/* Left: info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-label-lg font-bold text-on-surface">{m.name}</span>
                    <span className={`px-2 py-0.5 text-[10px] font-bold rounded-full uppercase tracking-wide ${
                      m.engine === 'qwen3_asr'
                        ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
                        : 'bg-surface-variant text-on-surface-variant'
                    }`}>
                      {m.engine === 'qwen3_asr' ? 'Qwen3-ASR' : 'Whisper'}
                    </span>
                    {isActive && (
                      <span className="px-2 py-0.5 bg-primary text-on-primary text-[10px] font-bold rounded-full uppercase tracking-wide">
                        Active
                      </span>
                    )}
                    {m.downloaded && !isActive && (
                      <span className="px-2 py-0.5 bg-tertiary/20 text-tertiary text-[10px] font-bold rounded-full uppercase tracking-wide">
                        Downloaded
                      </span>
                    )}
                  </div>
                  <p className="text-body-sm text-on-surface-variant mt-0.5">{m.description}</p>
                  <div className="flex items-center gap-3 mt-1.5 text-label-sm text-on-surface-variant">
                    <span className="flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">hard_drive</span>
                      {fmtSize(m.size_mb)}
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">language</span>
                      {langLabel}
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">speed</span>
                      <span className={{
                        'very fast': 'text-green-600 dark:text-green-400',
                        'fast':      'text-green-600 dark:text-green-400',
                        'medium':    'text-yellow-600 dark:text-yellow-400',
                        'slow':      'text-orange-600 dark:text-orange-400',
                      }[m.speed] ?? ''}>
                        {m.speed}
                      </span>
                    </span>
                  </div>
                </div>

                {/* Right: actions */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  {isDownloading ? (
                    <span className="text-body-sm text-secondary italic">
                      {progress && progress.total_mb > 0
                        ? `${progress.downloaded_mb.toFixed(0)} / ${fmtSize(progress.total_mb)} · ${Math.round(progress.downloaded_mb / progress.total_mb * 100)}%`
                        : 'Starting…'}
                    </span>
                  ) : m.downloaded ? (
                    <>
                      {!isActive && (
                        <button
                          onClick={() => handleSetActive(m.name)}
                          className="px-3 py-1.5 border border-primary text-primary rounded-lg text-label-sm font-semibold hover:bg-primary/10 transition-colors"
                        >
                          Set active
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(m.name)}
                        disabled={isActive}
                        title={isActive ? 'Cannot delete the active model' : 'Delete from disk'}
                        className="material-symbols-outlined text-[18px] text-outline hover:text-error transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        delete
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => handleDownload(m.name)}
                      disabled={!!downloading}
                      className="px-3 py-1.5 bg-surface-container-high text-on-surface rounded-lg text-label-sm font-semibold hover:bg-surface-container-highest transition-colors disabled:opacity-50 flex items-center gap-1.5"
                    >
                      <span className="material-symbols-outlined text-[14px]">download</span>
                      Download
                    </button>
                  )}
                </div>
              </div>

              {/* Progress bar */}
              {isDownloading && progress && progress.total_mb > 0 && (
                <div className="mt-3 flex items-center gap-3">
                  <div className="w-40 h-2 bg-surface-container-high rounded-full overflow-hidden flex-shrink-0">
                    <div
                      className="h-full bg-primary rounded-full transition-all duration-500"
                      style={{ width: `${Math.min(100, (progress.downloaded_mb / progress.total_mb) * 100).toFixed(1)}%` }}
                    />
                  </div>
                  <span className="text-label-sm text-secondary tabular-nums">
                    {Math.round(progress.downloaded_mb / progress.total_mb * 100)}%
                    {speedMbps !== null && <> · {speedMbps.toFixed(1)} MB/s</>}
                  </span>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
