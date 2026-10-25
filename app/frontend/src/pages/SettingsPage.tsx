import { useEffect, useRef, useState } from 'react'
import {
  getSettings, saveAppSettings, saveSettings, resetSettings, getModels, getSttModels,
  downloadSttModel, getSttModelDownloadStatus, deleteSttModel, getYtdlpVersion, updateYtdlp,
  AppSettings, StageSettings, SttModelInfo,
} from '../api'
import { BOXED_LAYOUT_EVENT, BOXED_LAYOUT_KEY } from '../App'

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

const INPUT = (err?: boolean) =>
  `w-full bg-surface-container-low border ${err ? 'border-error' : 'border-outline-variant'} rounded-lg p-3 text-body-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all`

const SELECT = (err?: boolean) =>
  `w-full bg-surface-container-low border ${err ? 'border-error' : 'border-outline-variant'} rounded-lg p-3 text-body-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all`

const TEXTAREA = `w-full bg-surface-container-low border border-outline-variant rounded-lg p-3 text-body-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all resize-y`

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] text-on-surface-variant mt-1">{children}</p>
}

function WarnBanner({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 p-4 bg-error-container/20 border border-error/30 rounded-lg">
      <span className="material-symbols-outlined text-error text-[18px] flex-shrink-0 mt-0.5">warning</span>
      <span className="text-body-sm text-on-error-container">{children}</span>
    </div>
  )
}

function SavedToast({ msg }: { msg: string }) {
  if (!msg) return null
  return <span className="text-body-sm text-tertiary font-medium">{msg}</span>
}

// ---------------------------------------------------------------------------
// General tab
// ---------------------------------------------------------------------------

interface GeneralPanelProps {
  initial: AppSettings
  onSaved: (s: AppSettings) => void
}

function GeneralPanel({ initial, onSaved }: GeneralPanelProps) {
  const [ollamaUrl, setOllamaUrl]           = useState(initial.ollama_url ?? '')
  const [useCustomYtdlp, setUseCustomYtdlp] = useState(!!initial.ytdlp_path)
  const [ytdlpPath, setYtdlpPath]           = useState(initial.ytdlp_path ?? '')
  const [cookiesPath, setCookiesPath]       = useState(initial.cookies_path ?? '')
  const [parallelWorkers, setParallelWorkers] = useState(initial.parallel_workers ?? '1')
  const [parallelError, setParallelError]   = useState('')
  const [saving, setSaving]                 = useState(false)
  const [toast, setToast]                   = useState('')
  const [ytdlpVersion, setYtdlpVersion]     = useState<string | null>(null)
  const [ytdlpUpdateStatus, setYtdlpUpdateStatus] = useState<string>('idle')
  const fileRef = useRef<HTMLInputElement>(null)
  const updatePollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    setOllamaUrl(initial.ollama_url ?? '')
    setUseCustomYtdlp(!!initial.ytdlp_path)
    setYtdlpPath(initial.ytdlp_path ?? '')
    setCookiesPath(initial.cookies_path ?? '')
    setParallelWorkers(initial.parallel_workers ?? '1')
  }, [initial])

  useEffect(() => {
    getYtdlpVersion().then(r => {
      setYtdlpVersion(r.version)
      setYtdlpUpdateStatus(r.update_status)
    })
    return () => { if (updatePollRef.current) clearInterval(updatePollRef.current) }
  }, [])

  function showToast(msg: string) { setToast(msg); setTimeout(() => setToast(''), 2500) }

  async function handleSave() {
    const pw = parseInt(parallelWorkers, 10)
    if (isNaN(pw) || pw < 1 || pw > 16) {
      setParallelError('Must be an integer between 1 and 16')
      return
    }
    setParallelError('')
    setSaving(true)
    const start = Date.now()
    try {
      const saved = await saveAppSettings({
        ollama_url: ollamaUrl || null,
        ytdlp_path: useCustomYtdlp ? (ytdlpPath || null) : null,
        cookies_path: cookiesPath || null,
        parallel_workers: String(pw),
      })
      onSaved(saved)
      showToast('Saved')
    } catch {
      showToast('Failed to save')
    } finally {
      const elapsed = Date.now() - start
      const remaining = 500 - elapsed
      if (remaining > 0) await new Promise(r => setTimeout(r, remaining))
      setSaving(false)
    }
  }

  async function handleCookiesUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const text = await file.text()
    const formData = new FormData()
    formData.append('file', new Blob([text], { type: 'text/plain' }), file.name)
    try {
      const res = await fetch('/api/settings/upload-cookies', { method: 'POST', body: formData })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setCookiesPath(data.path)
      showToast('Cookies uploaded')
    } catch {
      showToast('Upload failed')
    }
    if (fileRef.current) fileRef.current.value = ''
  }

  async function handleUpdateYtdlp() {
    setYtdlpUpdateStatus('updating')
    try {
      await updateYtdlp()
      updatePollRef.current = setInterval(async () => {
        const r = await getYtdlpVersion()
        setYtdlpVersion(r.version)
        setYtdlpUpdateStatus(r.update_status)
        if (r.update_status !== 'updating') {
          if (updatePollRef.current) clearInterval(updatePollRef.current)
          showToast(r.update_status === 'done' ? 'yt-dlp updated' : 'Update failed')
        }
      }, 1500)
    } catch {
      setYtdlpUpdateStatus('failed')
      showToast('Update failed')
    }
  }

  const missing = [
    !ollamaUrl  && 'Ollama URL',
    !cookiesPath && 'Cookies path',
  ].filter(Boolean)

  return (
    <div className="space-y-5">
      {missing.length > 0 && (
        <WarnBanner>Required fields missing: {missing.join(', ')}</WarnBanner>
      )}

      {/* Ollama URL */}
      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface flex items-center gap-1">
          Ollama URL <span className="text-error">*</span>
        </label>
        <input
          type="text"
          className={INPUT(!ollamaUrl)}
          value={ollamaUrl}
          onChange={e => setOllamaUrl(e.target.value)}
          placeholder="http://localhost:11434"
        />
      </div>

      {/* yt-dlp section */}
      <div className="space-y-3 p-4 bg-surface-container-low rounded-xl border border-outline-variant">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-label-md text-on-surface font-medium">yt-dlp</p>
            <p className="text-[11px] text-on-surface-variant mt-0.5">
              {useCustomYtdlp ? 'Custom binary path' : 'Bundled (recommended)'}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {!useCustomYtdlp && (
              <div className="flex items-center gap-2">
                <span className="text-body-sm text-on-surface-variant">
                  {ytdlpUpdateStatus === 'updating'
                    ? 'Updating…'
                    : ytdlpVersion
                      ? <span>v{ytdlpVersion}</span>
                      : <span className="text-on-surface-variant/50">—</span>
                  }
                </span>
                <button
                  onClick={handleUpdateYtdlp}
                  disabled={ytdlpUpdateStatus === 'updating'}
                  className="px-3 py-1 text-[11px] font-semibold rounded-lg bg-secondary-container text-on-secondary-container hover:opacity-90 active:scale-95 transition-all disabled:opacity-50"
                >
                  {ytdlpUpdateStatus === 'updating' ? '…' : 'Update'}
                </button>
              </div>
            )}
            {/* Toggle */}
            <button
              role="switch"
              aria-checked={useCustomYtdlp}
              onClick={() => setUseCustomYtdlp(v => !v)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${useCustomYtdlp ? 'bg-primary' : 'bg-surface-container-highest'}`}
            >
              <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${useCustomYtdlp ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
            <span className="text-[11px] text-on-surface-variant w-16">Custom path</span>
          </div>
        </div>
        {useCustomYtdlp && (
          <div className="space-y-1.5">
            <input
              type="text"
              className={INPUT(!ytdlpPath)}
              value={ytdlpPath}
              onChange={e => setYtdlpPath(e.target.value)}
              placeholder="C:/ytdlp/yt-dlp.exe"
            />
            <Hint>Absolute path to yt-dlp executable on the server.</Hint>
          </div>
        )}
      </div>

      {/* Cookies path with upload */}
      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface flex items-center gap-1">
          Cookies path <span className="text-error">*</span>
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            className={INPUT(!cookiesPath) + ' flex-1'}
            value={cookiesPath}
            onChange={e => setCookiesPath(e.target.value)}
            placeholder="../data/www.youtube.com_cookies.txt"
          />
          <button
            onClick={() => fileRef.current?.click()}
            className="px-5 bg-surface-container-high text-on-surface text-label-md rounded-lg hover:bg-surface-dim transition-colors active:scale-95"
          >
            Upload
          </button>
        </div>
        <input ref={fileRef} type="file" accept=".txt" className="hidden" onChange={handleCookiesUpload} />
        <Hint>Export from Chrome via "Get cookies.txt LOCALLY" extension.</Hint>
      </div>

      {/* Parallel workers */}
      <div className="space-y-1.5 w-1/4 min-w-[140px]">
        <label className="text-label-md text-on-surface">Parallel workers</label>
        <input
          type="number"
          min={1}
          max={16}
          className={INPUT(!!parallelError)}
          value={parallelWorkers}
          onChange={e => { setParallelWorkers(e.target.value); setParallelError('') }}
        />
        {parallelError
          ? <p className="text-[11px] text-error mt-1">{parallelError}</p>
          : <Hint>Number of paragraphs/chunks processed simultaneously. Should match OLLAMA_NUM_PARALLEL.</Hint>
        }
      </div>

      {/* Actions */}
      <div className="flex items-center gap-4 pt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2.5 bg-primary text-on-primary text-label-md font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <SavedToast msg={toast} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Boxed (floating) layout toggle — localStorage only, no backend
// ---------------------------------------------------------------------------

function BoxedLayoutToggle() {
  const [enabled, setEnabled] = useState(() => localStorage.getItem(BOXED_LAYOUT_KEY) === 'true')

  function handleToggle() {
    const next = !enabled
    setEnabled(next)
    localStorage.setItem(BOXED_LAYOUT_KEY, String(next))
    window.dispatchEvent(new CustomEvent<boolean>(BOXED_LAYOUT_EVENT, { detail: next }))
  }

  return (
    <div className="flex items-start gap-4 p-4 bg-surface-container rounded-lg border border-outline-variant/50">
      <button
        id="boxed-layout"
        role="switch"
        aria-checked={enabled}
        onClick={handleToggle}
        className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 mt-0.5 ${enabled ? 'bg-primary' : 'bg-surface-container-highest'}`}
      >
        <span
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ${enabled ? 'translate-x-5' : 'translate-x-0'}`}
        />
      </button>
      <div className="flex-1">
        <label htmlFor="boxed-layout" className="text-label-md text-on-surface block cursor-pointer">
          Boxed layout (floating UI)
        </label>
        <Hint>
          Wraps the app in a centered rounded container with shadow. Best on large or ultrawide monitors.
        </Hint>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Force Map-Reduce toggle
// ---------------------------------------------------------------------------

function ForceMapReduceToggle({ value, onSaved }: { value: boolean; onSaved: (s: AppSettings) => void }) {
  const [checked, setChecked] = useState(value)
  const [toast, setToast]     = useState('')

  function showToast(msg: string) { setToast(msg); setTimeout(() => setToast(''), 2500) }

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const next = e.target.checked
    setChecked(next)
    try {
      const saved = await saveAppSettings({ force_map_reduce: String(next) })
      onSaved(saved)
      showToast('Saved')
    } catch {
      setChecked(!next)
      showToast('Failed to save')
    }
  }

  return (
    <div className="flex items-start gap-3 p-4 bg-surface-container rounded-lg border border-outline-variant/50">
      <input
        id="force-map-reduce"
        type="checkbox"
        checked={checked}
        onChange={handleChange}
        className="mt-1 w-4 h-4 rounded accent-primary focus:ring-primary/20"
      />
      <div className="flex-1">
        <label htmlFor="force-map-reduce" className="text-label-md text-on-surface block cursor-pointer">
          Force Map-Reduce mode
        </label>
        <Hint>Overrides auto-detection — always use Map-Reduce regardless of text length. For testing only.</Hint>
      </div>
      <SavedToast msg={toast} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Model-only selector (auto-saves on change)
// ---------------------------------------------------------------------------

function ModelOnlyPanel({ stage, initial, models, modelsOnline, onSaved }: {
  stage: string
  initial: StageSettings
  models: string[]
  modelsOnline: boolean
  onSaved: (s: StageSettings) => void
}) {
  const [model, setModel] = useState(initial.model ?? '')
  const [toast, setToast] = useState('')

  useEffect(() => { setModel(initial.model ?? '') }, [initial])

  function showToast(msg: string) { setToast(msg); setTimeout(() => setToast(''), 2500) }

  async function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const next = e.target.value
    setModel(next)
    try {
      const saved = await saveSettings(stage, {
        system_prompt: initial.system_prompt,
        user_prompt_template: initial.user_prompt_template,
        model: next || null,
      })
      onSaved(saved)
      showToast('Saved')
    } catch {
      setModel(initial.model ?? '')
      showToast('Failed to save')
    }
  }

  return (
    <div className="flex items-center gap-3">
      <select
        value={model}
        onChange={handleChange}
        disabled={!modelsOnline}
        className={SELECT(!model) + ' flex-1'}
        title={!modelsOnline ? 'Ollama offline — cannot load models' : undefined}
      >
        <option value="">— Select your model —</option>
        {models.map(m => <option key={m} value={m}>{m}</option>)}
      </select>
      <SavedToast msg={toast} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stage panel (model + system_prompt + user_prompt_template + save/reset)
// ---------------------------------------------------------------------------

interface StagePanelProps {
  stage: string
  initial: StageSettings
  models: string[]
  modelsOnline: boolean
  hideModel?: boolean
}

function StagePanel({ stage, initial, models, modelsOnline, hideModel }: StagePanelProps) {
  const [systemPrompt, setSystemPrompt] = useState(initial.system_prompt ?? '')
  const [userPrompt, setUserPrompt]     = useState(initial.user_prompt_template ?? '')
  const [model, setModel]               = useState(initial.model ?? '')
  const [saving, setSaving]             = useState(false)
  const [toast, setToast]               = useState('')

  useEffect(() => {
    setSystemPrompt(initial.system_prompt ?? '')
    setUserPrompt(initial.user_prompt_template ?? '')
    setModel(initial.model ?? '')
  }, [initial])

  function showToast(msg: string) { setToast(msg); setTimeout(() => setToast(''), 2500) }

  async function handleSave() {
    setSaving(true)
    const start = Date.now()
    try {
      await saveSettings(stage, {
        system_prompt: systemPrompt || null,
        user_prompt_template: userPrompt || null,
        model: model || null,
      })
      showToast('Saved')
    } catch {
      showToast('Failed to save')
    } finally {
      const elapsed = Date.now() - start
      const remaining = 500 - elapsed
      if (remaining > 0) await new Promise(r => setTimeout(r, remaining))
      setSaving(false)
    }
  }

  async function handleReset() {
    setSaving(true)
    try {
      const defaults = await resetSettings(stage)
      setSystemPrompt(defaults.system_prompt ?? '')
      setUserPrompt(defaults.user_prompt_template ?? '')
      setModel(defaults.model ?? '')
      showToast('Reset to defaults')
    } catch {
      showToast('Failed to reset')
    } finally {
      setSaving(false)
    }
  }

  const missingModel = !hideModel && !model

  return (
    <div className="space-y-5">
      {missingModel && (
        <WarnBanner>No model selected — AI stage will not run until a model is chosen.</WarnBanner>
      )}

      {!hideModel && (
        <div className="space-y-1.5">
          <label className="text-label-md text-on-surface flex items-center gap-1">
            Model <span className="text-error">*</span>
          </label>
          <select
            value={model}
            onChange={e => setModel(e.target.value)}
            disabled={!modelsOnline}
            className={SELECT(missingModel)}
            title={!modelsOnline ? 'Ollama offline — cannot load models' : undefined}
          >
            <option value="">— Select your model —</option>
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          {!modelsOnline && <Hint>Ollama offline — model list unavailable</Hint>}
        </div>
      )}

      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface">System prompt</label>
        <textarea
          className={TEXTAREA}
          value={systemPrompt}
          onChange={e => setSystemPrompt(e.target.value)}
          rows={4}
          placeholder="System prompt for this stage…"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface">User prompt template</label>
        <textarea
          className={TEXTAREA}
          value={userPrompt}
          onChange={e => setUserPrompt(e.target.value)}
          rows={10}
          placeholder="Use {text} as the placeholder for input text…"
        />
        <Hint>Use <code className="bg-surface-container-high px-1 rounded text-[11px]">&#123;text&#125;</code> as placeholder for the input text.</Hint>
      </div>

      <div className="flex items-center gap-4 pt-1">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2.5 bg-primary text-on-primary text-label-md font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          onClick={handleReset}
          disabled={saving}
          className="px-6 py-2.5 bg-surface-container-high text-on-surface text-label-md rounded-lg hover:bg-surface-dim active:scale-[0.98] transition-all disabled:opacity-50"
        >
          Reset to defaults
        </button>
        <SavedToast msg={toast} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Speech-to-Text tab
// ---------------------------------------------------------------------------

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

function SttPanel({ initial, sttModels, onSaved, onReloadModels }: SttPanelProps) {
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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type TabId = 'general' | 'cleanup' | 'summarization' | 'chat' | 'stt'
type SummSubTab = 'single_pass' | 'map_reduce'
type MapReduceStep = 'extract' | 'combine'

const TABS: { id: TabId; label: string }[] = [
  { id: 'general',       label: 'General' },
  { id: 'cleanup',       label: 'AI Cleanup' },
  { id: 'summarization', label: 'Summarization' },
  { id: 'chat',          label: 'Chat' },
  { id: 'stt',           label: 'Speech-to-Text' },
]

export default function SettingsPage() {
  const [activeTab, setActiveTab]   = useState<TabId>('general')
  const [summSubTab, setSummSubTab] = useState<SummSubTab>('single_pass')
  const [mapReduceStep, setMapReduceStep] = useState<MapReduceStep>('extract')

  const [appSettings, setAppSettings]   = useState<AppSettings | null>(null)
  const [cleanup, setCleanup]           = useState<StageSettings | null>(null)
  const [summarization, setSummarization] = useState<StageSettings | null>(null)
  const [summExtract, setSummExtract]   = useState<StageSettings | null>(null)
  const [summCombine, setSummCombine]   = useState<StageSettings | null>(null)
  const [chat, setChat]                 = useState<StageSettings | null>(null)
  const [models, setModels]             = useState<string[]>([])
  const [modelsOnline, setModelsOnline] = useState(true)
  const [sttModels, setSttModels]       = useState<SttModelInfo[]>([])
  const [error, setError]               = useState('')

  useEffect(() => {
    getSettings()
      .then(s => {
        setAppSettings(s.app)
        setCleanup(s.cleanup)
        setSummarization(s.summarization)
        setSummExtract(s.summarization_extract)
        setSummCombine(s.summarization_combine)
        setChat(s.chat)
      })
      .catch(() => setError('Could not load settings'))

    getModels()
      .then(list => { setModels(list); setModelsOnline(true) })
      .catch(() => setModelsOnline(false))

    getSttModels().then(setSttModels).catch(() => {})
  }, [])

  function reloadSttModels() {
    getSttModels().then(setSttModels).catch(() => {})
  }

  if (error) return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto">
      <div className="bg-error-container border border-error/30 rounded-xl p-6 text-on-error-container">{error}</div>
    </div>
  )

  if (!appSettings || !cleanup || !summarization || !summExtract || !summCombine || !chat) return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto">
      <div className="py-16 text-center text-secondary text-body-md">Loading…</div>
    </div>
  )

  return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto space-y-6">

      {/* Page header */}
      <div>
        <h2 className="text-headline-xl font-bold text-on-surface">Settings</h2>
        <p className="text-body-md text-on-surface-variant mt-1">Configure the application. All settings are stored in the database.</p>
      </div>

      {/* Main card */}
      <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm overflow-hidden">

        {/* Tab bar */}
        <div className="flex border-b border-outline-variant px-6">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`py-4 px-6 text-label-md border-b-2 transition-all ${
                activeTab === tab.id
                  ? 'border-primary text-primary font-bold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="p-6">

          {/* General */}
          {activeTab === 'general' && (
            <div className="space-y-6">
              <GeneralPanel initial={appSettings} onSaved={setAppSettings} />
              <div className="border-t border-outline-variant pt-5 space-y-3">
                <p className="text-label-sm text-on-surface-variant uppercase tracking-wider font-bold">Display</p>
                <BoxedLayoutToggle />
              </div>
            </div>
          )}

          {/* AI Cleanup */}
          {activeTab === 'cleanup' && (
            <div className="space-y-5">
              <div className="space-y-1.5">
                <label className="text-label-md text-on-surface flex items-center gap-1">
                  Model <span className="text-error">*</span>
                </label>
                <ModelOnlyPanel
                  stage="cleanup"
                  initial={cleanup}
                  models={models}
                  modelsOnline={modelsOnline}
                  onSaved={setCleanup}
                />
              </div>
              <StagePanel
                stage="cleanup"
                initial={cleanup}
                models={models}
                modelsOnline={modelsOnline}
                hideModel
              />
            </div>
          )}

          {/* Summarization */}
          {activeTab === 'summarization' && (
            <div className="space-y-5">

              {/* Force Map-Reduce */}
              <ForceMapReduceToggle
                value={appSettings.force_map_reduce === 'true'}
                onSaved={setAppSettings}
              />

              {/* Shared model selector */}
              <div className="space-y-1.5">
                <label className="text-label-md text-on-surface flex items-center gap-1">
                  Model <span className="text-error">*</span>
                </label>
                <ModelOnlyPanel
                  stage="summarization"
                  initial={summarization}
                  models={models}
                  modelsOnline={modelsOnline}
                  onSaved={setSummarization}
                />
              </div>

              {/* Sub-tabs: Single Pass / Map-Reduce */}
              <div className="border border-outline-variant rounded-lg overflow-hidden">
                <div className="bg-surface-container flex border-b border-outline-variant">
                  {([
                    { id: 'single_pass' as const, label: 'Single Pass' },
                    { id: 'map_reduce'  as const, label: 'Map-Reduce' },
                  ]).map(t => (
                    <button
                      key={t.id}
                      onClick={() => setSummSubTab(t.id)}
                      className={`px-6 py-2.5 text-label-md transition-colors ${
                        summSubTab === t.id
                          ? 'bg-surface-container-lowest text-primary border-b-2 border-primary font-bold'
                          : 'text-on-surface-variant hover:bg-surface-container-high'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>

                <div className="p-6">
                  {summSubTab === 'single_pass' && (
                    <StagePanel
                      stage="summarization"
                      initial={summarization}
                      models={models}
                      modelsOnline={modelsOnline}
                      hideModel
                    />
                  )}

                  {summSubTab === 'map_reduce' && (
                    <div className="space-y-5">
                      {/* Step tabs */}
                      <div className="flex gap-1 border-b border-outline-variant pb-0 -mx-6 px-6">
                        {([
                          { id: 'extract' as const, label: 'Step 1 — Extract (per chunk)' },
                          { id: 'combine' as const, label: 'Step 2 — Combine (all chunks)' },
                        ]).map(s => (
                          <button
                            key={s.id}
                            onClick={() => setMapReduceStep(s.id)}
                            className={`px-4 py-2 text-label-md border-b-2 transition-all -mb-px ${
                              mapReduceStep === s.id
                                ? 'border-primary text-primary font-bold'
                                : 'border-transparent text-on-surface-variant hover:text-on-surface'
                            }`}
                          >
                            {s.label}
                          </button>
                        ))}
                      </div>

                      {mapReduceStep === 'extract' && (
                        <StagePanel
                          stage="summarization_extract"
                          initial={summExtract}
                          models={models}
                          modelsOnline={modelsOnline}
                          hideModel
                        />
                      )}
                      {mapReduceStep === 'combine' && (
                        <StagePanel
                          stage="summarization_combine"
                          initial={summCombine}
                          models={models}
                          modelsOnline={modelsOnline}
                          hideModel
                        />
                      )}
                    </div>
                  )}
                </div>
              </div>

            </div>
          )}

          {/* Chat */}
          {activeTab === 'chat' && (
            <div className="space-y-5">
              <p className="text-body-sm text-on-surface-variant">
                Model used for chat conversations on the Result page. If not set, falls back to the Summarization model.
              </p>
              <div className="space-y-1.5">
                <label className="text-label-md text-on-surface">Model</label>
                <ModelOnlyPanel
                  stage="chat"
                  initial={chat}
                  models={models}
                  modelsOnline={modelsOnline}
                  onSaved={setChat}
                />
              </div>
            </div>
          )}

          {/* Speech-to-Text */}
          {activeTab === 'stt' && (
            <SttPanel
              initial={appSettings}
              sttModels={sttModels}
              onSaved={setAppSettings}
              onReloadModels={reloadSttModels}
            />
          )}

        </div>
      </div>
    </div>
  )
}
