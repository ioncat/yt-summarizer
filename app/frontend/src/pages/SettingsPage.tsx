import { useEffect, useRef, useState } from 'react'
import {
  getSettings, saveAppSettings, saveSettings, resetSettings, getModels,
  AppSettings, StageSettings,
} from '../api'

// ---------------------------------------------------------------------------
// General tab
// ---------------------------------------------------------------------------

interface GeneralPanelProps {
  initial: AppSettings
  onSaved: (s: AppSettings) => void
}

function GeneralPanel({ initial, onSaved }: GeneralPanelProps) {
  const [ollamaUrl, setOllamaUrl] = useState(initial.ollama_url ?? '')
  const [ytdlpPath, setYtdlpPath] = useState(initial.ytdlp_path ?? '')
  const [cookiesPath, setCookiesPath] = useState(initial.cookies_path ?? '')
  const [parallelWorkers, setParallelWorkers] = useState(initial.parallel_workers ?? '1')
  const [parallelError, setParallelError] = useState('')
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setOllamaUrl(initial.ollama_url ?? '')
    setYtdlpPath(initial.ytdlp_path ?? '')
    setCookiesPath(initial.cookies_path ?? '')
    setParallelWorkers(initial.parallel_workers ?? '1')
  }, [initial])

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(''), 2500)
  }

  async function handleSave() {
    // Validate parallel_workers
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
        ytdlp_path: ytdlpPath || null,
        cookies_path: cookiesPath || null,
        parallel_workers: String(pw),
      })
      onSaved(saved)
      showToast('Saved')
    } catch (err) {
      console.error('[Settings/General] saveAppSettings failed:', err)
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
    } catch (err) {
      console.error('[Settings/General] upload-cookies failed:', err)
      showToast('Upload failed')
    }
    if (fileRef.current) fileRef.current.value = ''
  }

  const missingFields = [
    !ollamaUrl && 'Ollama URL',
    !ytdlpPath && 'yt-dlp path',
    !cookiesPath && 'Cookies path',
  ].filter(Boolean)

  const inputClass = (missing: boolean) =>
    `w-full px-4 py-2.5 bg-surface-container-low border rounded-lg text-body-md focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all ${missing ? 'border-error/60' : 'border-outline-variant focus:border-primary'}`

  return (
    <div className="space-y-6">
      {missingFields.length > 0 && (
        <div className="flex items-center gap-2 bg-error-container text-on-error-container rounded-lg px-4 py-3 text-body-sm">
          <span className="material-symbols-outlined flex-shrink-0" style={{ fontSize: '16px' }}>warning</span>
          Required fields missing: {missingFields.join(', ')}
        </div>
      )}

      <div className="space-y-2">
        <label className="block text-label-md text-on-surface-variant">Ollama URL <span className="text-error">*</span></label>
        <input type="text" className={inputClass(!ollamaUrl)} value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)} placeholder="http://localhost:11434" />
      </div>

      <div className="space-y-2">
        <label className="block text-label-md text-on-surface-variant">yt-dlp path <span className="text-error">*</span></label>
        <input type="text" className={inputClass(!ytdlpPath)} value={ytdlpPath} onChange={e => setYtdlpPath(e.target.value)} placeholder="C:/ytdlp/yt-dlp.exe" />
        <p className="text-body-sm text-secondary">Path to yt-dlp executable on the server.</p>
      </div>

      <div className="space-y-2">
        <label className="block text-label-md text-on-surface-variant">Cookies path <span className="text-error">*</span></label>
        <div className="flex gap-2">
          <input type="text" className={`flex-1 px-4 py-2.5 bg-surface-container-low border rounded-lg text-body-md focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all ${!cookiesPath ? 'border-error/60' : 'border-outline-variant focus:border-primary'}`} value={cookiesPath} onChange={e => setCookiesPath(e.target.value)} placeholder="../data/www.youtube.com_cookies.txt" />
          <button className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant border border-outline-variant rounded-lg text-label-md hover:bg-surface-container-highest active:scale-95 transition-all" onClick={() => fileRef.current?.click()}>Upload</button>
        </div>
        <input ref={fileRef} type="file" accept=".txt" className="hidden" onChange={handleCookiesUpload} />
        <p className="text-body-sm text-secondary">Export from Chrome via "Get cookies.txt LOCALLY" extension.</p>
      </div>

      <div className="space-y-2">
        <label className="block text-label-md text-on-surface-variant">Parallel workers</label>
        <input type="number" min={1} max={16} className={`w-24 px-4 py-2.5 bg-surface-container-low border rounded-lg text-body-md focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all ${parallelError ? 'border-error/60' : 'border-outline-variant focus:border-primary'}`} value={parallelWorkers} onChange={e => { setParallelWorkers(e.target.value); setParallelError('') }} />
        {parallelError && <p className="text-body-sm text-error">{parallelError}</p>}
        <p className="text-body-sm text-secondary">Paragraphs/chunks processed simultaneously. Should match <code className="text-xs bg-surface-container-high px-1 py-0.5 rounded">OLLAMA_NUM_PARALLEL</code> on your Ollama server (default 1 = sequential).</p>
      </div>

      <div className="flex items-center gap-3 pt-2">
        <button className="px-6 py-2.5 bg-primary text-on-primary rounded-lg text-label-md font-semibold hover:opacity-90 active:scale-95 transition-all disabled:opacity-40" onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        {toast && <span className="text-label-sm text-tertiary font-semibold">{toast}</span>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Force Map-Reduce toggle (Summarization tab only)
// ---------------------------------------------------------------------------

interface ForceMapReduceProps {
  value: boolean
  onSaved: (s: AppSettings) => void
}

function ForceMapReduceToggle({ value, onSaved }: ForceMapReduceProps) {
  const [checked, setChecked] = useState(value)
  const [toast, setToast] = useState('')

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(''), 2500)
  }

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
    <div className="flex items-start gap-3 pb-6 mb-6 border-b border-outline-variant">
      <input type="checkbox" id="force-map-reduce" className="w-4 h-4 accent-primary mt-0.5 cursor-pointer" checked={checked} onChange={handleChange} />
      <div>
        <label htmlFor="force-map-reduce" className="text-label-md text-on-surface cursor-pointer">
          Force Map-Reduce mode {toast && <span className="text-label-sm text-tertiary font-semibold ml-2">{toast}</span>}
        </label>
        <p className="text-body-sm text-secondary mt-1">Overrides auto-detection — always use Map-Reduce regardless of text length. For testing only.</p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AI stage tab (cleanup / summarization)
// ---------------------------------------------------------------------------

interface StagePanelProps {
  stage: string
  initial: StageSettings
  models: string[]
  modelsOnline: boolean
  locked?: boolean
  hideModel?: boolean
  label?: string
}

// Model-only selector that saves just the model field for a stage
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
        className={`flex-1 px-4 py-2.5 bg-surface-container-low border rounded-lg text-body-md focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all appearance-none cursor-pointer ${!model ? 'border-error/60' : 'border-outline-variant focus:border-primary'}`}
        value={model}
        onChange={handleChange}
        disabled={!modelsOnline}
        title={!modelsOnline ? 'Ollama offline — cannot load models' : undefined}
      >
        <option value="">— Select your model —</option>
        {models.map(m => <option key={m} value={m}>{m}</option>)}
      </select>
      {toast && <span className="text-label-sm text-tertiary font-semibold">{toast}</span>}
    </div>
  )
}

function StagePanel({ stage, initial, models, modelsOnline, locked, hideModel, label }: StagePanelProps) {
  const [systemPrompt, setSystemPrompt] = useState(initial.system_prompt ?? '')
  const [userPrompt, setUserPrompt] = useState(initial.user_prompt_template ?? '')
  const [model, setModel] = useState(initial.model ?? '')
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState('')

  useEffect(() => {
    setSystemPrompt(initial.system_prompt ?? '')
    setUserPrompt(initial.user_prompt_template ?? '')
    setModel(initial.model ?? '')
  }, [initial])

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(''), 2500)
  }

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
    } catch (err) {
      console.error(`[Settings/${stage}] saveSettings failed:`, err)
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
    } catch (err) {
      console.error(`[Settings/${stage}] resetSettings failed:`, err)
      showToast('Failed to reset')
    } finally {
      setSaving(false)
    }
  }

  const missingModel = !locked && !hideModel && !model

  const taClass = 'w-full px-4 py-2.5 bg-surface-container-low border border-outline-variant rounded-lg text-body-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all resize-y disabled:opacity-60'

  return (
    <div className="space-y-6">
      {label && <h3 className="text-body-md font-semibold text-secondary">{label}</h3>}
      {locked && (
        <div className="flex items-center gap-2 bg-secondary-container text-on-secondary-container rounded-lg px-4 py-3 text-body-sm">
          <span className="material-symbols-outlined flex-shrink-0" style={{ fontSize: '16px' }}>lock</span>
          Phase 2 — coming soon. Settings locked.
        </div>
      )}
      {missingModel && (
        <div className="flex items-center gap-2 bg-error-container text-on-error-container rounded-lg px-4 py-3 text-body-sm">
          <span className="material-symbols-outlined flex-shrink-0" style={{ fontSize: '16px' }}>warning</span>
          No model selected — AI cleanup will not run until a model is chosen.
        </div>
      )}

      {!hideModel && (
        <div className="space-y-2">
          <label className="block text-label-md text-on-surface-variant">Model {!locked && <span className="text-error">*</span>}</label>
          <select
            className={`w-full px-4 py-2.5 bg-surface-container-low border rounded-lg text-body-md focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all appearance-none cursor-pointer disabled:opacity-60 ${missingModel ? 'border-error/60' : 'border-outline-variant focus:border-primary'}`}
            value={model}
            onChange={e => setModel(e.target.value)}
            disabled={locked || !modelsOnline}
            title={!modelsOnline ? 'Ollama offline — cannot load models' : undefined}
          >
            <option value="">— Select your model —</option>
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          {!modelsOnline && <p className="text-body-sm text-secondary">Ollama offline — model list unavailable</p>}
        </div>
      )}

      <div className="space-y-2">
        <label className="block text-label-md text-on-surface-variant">System prompt</label>
        <textarea className={taClass} value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)} disabled={locked} rows={4} placeholder="System prompt for this stage…" />
      </div>

      <div className="space-y-2">
        <label className="block text-label-md text-on-surface-variant">User prompt template</label>
        <textarea className={`${taClass} font-mono`} value={userPrompt} onChange={e => setUserPrompt(e.target.value)} disabled={locked} rows={10} placeholder="Use {text} as the placeholder for input text…" />
        {!locked && <p className="text-body-sm text-secondary">Use <code className="text-xs bg-surface-container-high px-1 py-0.5 rounded">{'{'+'text'+'}'}</code> as placeholder for the input text.</p>}
      </div>

      {!locked && (
        <div className="flex items-center gap-3 pt-2">
          <button className="px-6 py-2.5 bg-primary text-on-primary rounded-lg text-label-md font-semibold hover:opacity-90 active:scale-95 transition-all disabled:opacity-40" onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
          <button className="px-6 py-2.5 bg-surface-container-high text-on-surface-variant border border-outline-variant rounded-lg text-label-md hover:bg-surface-container-highest active:scale-95 transition-all disabled:opacity-40" onClick={handleReset} disabled={saving}>Reset to defaults</button>
          {toast && <span className="text-label-sm text-tertiary font-semibold">{toast}</span>}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type TabId = 'general' | 'cleanup' | 'summarization'
type SummSubTab = 'single_pass' | 'map_reduce'
type MapReduceStep = 'extract' | 'combine'

const TABS: { id: TabId; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'cleanup', label: 'AI Cleanup' },
  { id: 'summarization', label: 'Summarization' },
]

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<TabId>('general')
  const [summSubTab, setSummSubTab] = useState<SummSubTab>('single_pass')
  const [mapReduceStep, setMapReduceStep] = useState<MapReduceStep>('extract')
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null)
  const [cleanup, setCleanup] = useState<StageSettings | null>(null)
  const [summarization, setSummarization] = useState<StageSettings | null>(null)
  const [summExtract, setSummExtract] = useState<StageSettings | null>(null)
  const [summCombine, setSummCombine] = useState<StageSettings | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [modelsOnline, setModelsOnline] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getSettings()
      .then(s => {
        setAppSettings(s.app)
        setCleanup(s.cleanup)
        setSummarization(s.summarization)
        setSummExtract(s.summarization_extract)
        setSummCombine(s.summarization_combine)
      })
      .catch(err => { console.error('[Settings] getSettings failed:', err); setError('Could not load settings') })

    getModels()
      .then(list => { setModels(list); setModelsOnline(true) })
      .catch(err => { console.error('[Settings] getModels failed:', err); setModelsOnline(false) })
  }, [])

  if (error) return (
    <div className="p-6 md:p-gutter max-w-[1200px] mx-auto w-full">
      <div className="bg-error-container text-on-error-container rounded-xl px-6 py-4 text-body-md">{error}</div>
    </div>
  )

  if (!appSettings || !cleanup || !summarization || !summExtract || !summCombine) return (
    <div className="flex items-center justify-center py-16">
      <span className="material-symbols-outlined text-secondary" style={{ fontSize: '36px', animation: 'spin 1.2s linear infinite' }}>progress_activity</span>
    </div>
  )

  return (
    <div className="p-6 md:p-gutter max-w-[1200px] mx-auto w-full space-y-6">
      {/* Page header */}
      <div className="mb-2">
        <h2 className="text-headline-xl text-on-surface">Settings</h2>
        <p className="text-body-md text-on-surface-variant mt-1">Configure the application. All settings are stored in the database.</p>
      </div>

      {/* Tabbed card */}
      <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm overflow-hidden">
        {/* Tab header */}
        <div className="flex border-b border-outline-variant px-6">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`py-4 px-6 text-label-md border-b-2 transition-all ${
                activeTab === tab.id
                  ? 'border-primary text-primary font-bold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface'
              }`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="p-6 md:p-gutter">
          {activeTab === 'general' && (
            <GeneralPanel initial={appSettings} onSaved={setAppSettings} />
          )}
          {activeTab === 'cleanup' && (
            <StagePanel
              stage="cleanup"
              initial={cleanup}
              models={models}
              modelsOnline={modelsOnline}
            />
          )}
          {activeTab === 'summarization' && (() => {
            const subTabClass = (active: boolean) =>
              active
                ? 'px-4 py-2 text-label-md font-bold text-primary border-b-2 border-primary transition-colors'
                : 'px-4 py-2 text-label-md text-on-surface-variant hover:text-on-surface border-b-2 border-transparent transition-colors'
            return (
              <>
                <ForceMapReduceToggle value={appSettings.force_map_reduce === 'true'} onSaved={setAppSettings} />

                {/* Model selector — shared across modes */}
                <div className="space-y-2 pb-6 mb-6 border-b border-outline-variant">
                  <label className="block text-label-md text-on-surface-variant">Model <span className="text-error">*</span></label>
                  <ModelOnlyPanel stage="summarization" initial={summarization} models={models} modelsOnline={modelsOnline} onSaved={setSummarization} />
                </div>

                {/* Mode sub-tabs */}
                <div className="flex gap-4 border-b border-outline-variant mb-6">
                  <button className={subTabClass(summSubTab === 'single_pass')} onClick={() => setSummSubTab('single_pass')}>Single Pass</button>
                  <button className={subTabClass(summSubTab === 'map_reduce')} onClick={() => setSummSubTab('map_reduce')}>Map-Reduce</button>
                </div>

                {summSubTab === 'single_pass' && (
                  <StagePanel stage="summarization" initial={summarization} models={models} modelsOnline={modelsOnline} hideModel />
                )}
                {summSubTab === 'map_reduce' && (
                  <>
                    <div className="flex gap-4 border-b border-outline-variant mb-6">
                      <button className={subTabClass(mapReduceStep === 'extract')} onClick={() => setMapReduceStep('extract')}>Step 1 — Extract (per chunk)</button>
                      <button className={subTabClass(mapReduceStep === 'combine')} onClick={() => setMapReduceStep('combine')}>Step 2 — Combine (all chunks)</button>
                    </div>
                    {mapReduceStep === 'extract' && <StagePanel stage="summarization_extract" initial={summExtract} models={models} modelsOnline={modelsOnline} hideModel />}
                    {mapReduceStep === 'combine' && <StagePanel stage="summarization_combine" initial={summCombine} models={models} modelsOnline={modelsOnline} hideModel />}
                  </>
                )}
              </>
            )
          })()}
        </div>
      </div>
    </div>
  )
}
