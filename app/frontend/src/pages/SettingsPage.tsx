import { useEffect, useRef, useState } from 'react'
import {
  getSettings, saveAppSettings, saveSettings, resetSettings, getModels,
  AppSettings, StageSettings,
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
  const [ytdlpPath, setYtdlpPath]           = useState(initial.ytdlp_path ?? '')
  const [cookiesPath, setCookiesPath]       = useState(initial.cookies_path ?? '')
  const [parallelWorkers, setParallelWorkers] = useState(initial.parallel_workers ?? '1')
  const [parallelError, setParallelError]   = useState('')
  const [saving, setSaving]                 = useState(false)
  const [toast, setToast]                   = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setOllamaUrl(initial.ollama_url ?? '')
    setYtdlpPath(initial.ytdlp_path ?? '')
    setCookiesPath(initial.cookies_path ?? '')
    setParallelWorkers(initial.parallel_workers ?? '1')
  }, [initial])

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
        ytdlp_path: ytdlpPath || null,
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

  const missing = [
    !ollamaUrl  && 'Ollama URL',
    !ytdlpPath  && 'yt-dlp path',
    !cookiesPath && 'Cookies path',
  ].filter(Boolean)

  return (
    <div className="space-y-5">
      {missing.length > 0 && (
        <WarnBanner>Required fields missing: {missing.join(', ')}</WarnBanner>
      )}

      {/* Two-column row: Ollama URL + yt-dlp path */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
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
        <div className="space-y-1.5">
          <label className="text-label-md text-on-surface flex items-center gap-1">
            yt-dlp path <span className="text-error">*</span>
          </label>
          <input
            type="text"
            className={INPUT(!ytdlpPath)}
            value={ytdlpPath}
            onChange={e => setYtdlpPath(e.target.value)}
            placeholder="C:/ytdlp/yt-dlp.exe"
          />
          <Hint>Path to yt-dlp executable on the server.</Hint>
        </div>
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
// Page
// ---------------------------------------------------------------------------

type TabId = 'general' | 'cleanup' | 'summarization'
type SummSubTab = 'single_pass' | 'map_reduce'
type MapReduceStep = 'extract' | 'combine'

const TABS: { id: TabId; label: string }[] = [
  { id: 'general',       label: 'General' },
  { id: 'cleanup',       label: 'AI Cleanup' },
  { id: 'summarization', label: 'Summarization' },
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
  const [models, setModels]             = useState<string[]>([])
  const [modelsOnline, setModelsOnline] = useState(true)
  const [error, setError]               = useState('')

  useEffect(() => {
    getSettings()
      .then(s => {
        setAppSettings(s.app)
        setCleanup(s.cleanup)
        setSummarization(s.summarization)
        setSummExtract(s.summarization_extract)
        setSummCombine(s.summarization_combine)
      })
      .catch(() => setError('Could not load settings'))

    getModels()
      .then(list => { setModels(list); setModelsOnline(true) })
      .catch(() => setModelsOnline(false))
  }, [])

  if (error) return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto">
      <div className="bg-error-container border border-error/30 rounded-xl p-6 text-on-error-container">{error}</div>
    </div>
  )

  if (!appSettings || !cleanup || !summarization || !summExtract || !summCombine) return (
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

        </div>
      </div>
    </div>
  )
}
