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

  return (
    <div className="settings-section">
      {missingFields.length > 0 && (
        <div className="settings-warning">
          ⚠ Required fields missing: {missingFields.join(', ')}
        </div>
      )}

      <div className="form-group">
        <label>Ollama URL <span className="required-mark">*</span></label>
        <input
          type="text"
          value={ollamaUrl}
          onChange={e => setOllamaUrl(e.target.value)}
          placeholder="http://localhost:11434"
          className={!ollamaUrl ? 'input-missing' : ''}
        />
      </div>

      <div className="form-group">
        <label>yt-dlp path <span className="required-mark">*</span></label>
        <input
          type="text"
          value={ytdlpPath}
          onChange={e => setYtdlpPath(e.target.value)}
          placeholder="C:/ytdlp/yt-dlp.exe"
          className={!ytdlpPath ? 'input-missing' : ''}
        />
        <div className="field-hint">Path to yt-dlp executable on the server.</div>
      </div>

      <div className="form-group">
        <label>Cookies path <span className="required-mark">*</span></label>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            type="text"
            value={cookiesPath}
            onChange={e => setCookiesPath(e.target.value)}
            placeholder="../data/www.youtube.com_cookies.txt"
            className={!cookiesPath ? 'input-missing' : ''}
            style={{ flex: 1 }}
          />
          <button className="btn btn-secondary" onClick={() => fileRef.current?.click()}>
            Upload
          </button>
        </div>
        <input ref={fileRef} type="file" accept=".txt" style={{ display: 'none' }} onChange={handleCookiesUpload} />
        <div className="field-hint">Export from Chrome via "Get cookies.txt LOCALLY" extension.</div>
      </div>

      <div className="form-group">
        <label>Parallel workers</label>
        <input
          type="number"
          min={1}
          max={16}
          value={parallelWorkers}
          onChange={e => { setParallelWorkers(e.target.value); setParallelError('') }}
          style={{ maxWidth: '100px' }}
          className={parallelError ? 'input-missing' : ''}
        />
        {parallelError && <div className="field-hint" style={{ color: '#dc2626' }}>{parallelError}</div>}
        <div className="field-hint">
          Number of paragraphs/chunks processed simultaneously during cleanup and summarization.
          Should match <code>OLLAMA_NUM_PARALLEL</code> on your Ollama server (default 1 = sequential).
        </div>
      </div>

      <div className="actions">
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        {toast && <span className="settings-toast">{toast}</span>}
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
    <div className="settings-section" style={{ paddingBottom: '0.5rem', borderBottom: '1px solid #eee', marginBottom: '1rem' }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', cursor: 'pointer' }}>
        <input type="checkbox" checked={checked} onChange={handleChange} />
        <span>Force Map-Reduce mode</span>
        {toast && <span className="settings-toast" style={{ marginLeft: '0.5rem' }}>{toast}</span>}
      </label>
      <div className="field-hint" style={{ marginTop: '0.3rem' }}>
        Overrides auto-detection — always use Map-Reduce regardless of text length. For testing only.
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
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
      <select
        value={model}
        onChange={handleChange}
        disabled={!modelsOnline}
        className={!model ? 'input-missing' : ''}
        title={!modelsOnline ? 'Ollama offline — cannot load models' : undefined}
        style={{ flex: 1 }}
      >
        <option value="">— Select your model —</option>
        {models.map(m => <option key={m} value={m}>{m}</option>)}
      </select>
      {toast && <span className="settings-toast">{toast}</span>}
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

  return (
    <div className="settings-section">
      {label && <h3 style={{ margin: '0 0 1rem', fontSize: '0.95rem', color: '#555' }}>{label}</h3>}
      {locked && (
        <div className="settings-warning settings-warning-info">
          Phase 2 — coming soon. Settings locked.
        </div>
      )}
      {missingModel && (
        <div className="settings-warning">
          ⚠ No model selected — AI cleanup will not run until a model is chosen.
        </div>
      )}

      {!hideModel && (
        <div className="form-group">
          <label>Model {!locked && <span className="required-mark">*</span>}</label>
          <select
            value={model}
            onChange={e => setModel(e.target.value)}
            disabled={locked || !modelsOnline}
            className={missingModel ? 'input-missing' : ''}
            title={!modelsOnline ? 'Ollama offline — cannot load models' : undefined}
          >
            <option value="">— Select your model —</option>
            {models.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          {!modelsOnline && (
            <div className="field-hint">Ollama offline — model list unavailable</div>
          )}
        </div>
      )}

      <div className="form-group">
        <label>System prompt</label>
        <textarea
          className="settings-textarea"
          value={systemPrompt}
          onChange={e => setSystemPrompt(e.target.value)}
          disabled={locked}
          rows={4}
          placeholder="System prompt for this stage…"
        />
      </div>

      <div className="form-group">
        <label>User prompt template</label>
        <textarea
          className="settings-textarea"
          value={userPrompt}
          onChange={e => setUserPrompt(e.target.value)}
          disabled={locked}
          rows={10}
          placeholder="Use {text} as the placeholder for input text…"
        />
        {!locked && (
          <div className="field-hint">Use <code>&#123;text&#125;</code> as placeholder for the input text.</div>
        )}
      </div>

      {!locked && (
        <div className="actions">
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button className="btn btn-secondary" onClick={handleReset} disabled={saving}>
            Reset to defaults
          </button>
          {toast && <span className="settings-toast">{toast}</span>}
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
    <div className="container">
      <div className="card"><div className="error-box">{error}</div></div>
    </div>
  )

  if (!appSettings || !cleanup || !summarization || !summExtract || !summCombine) return (
    <div className="container">
      <div className="card"><div className="status-box"><div className="spinner" /></div></div>
    </div>
  )

  return (
    <div className="container">
      <h1>Settings</h1>
      <p className="subtitle">Configure the application. All settings are stored in the database.</p>

      <div className="card">
        <div className="result-tabs" style={{ marginBottom: 0 }}>
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`result-tab ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div style={{ paddingTop: '1.5rem' }}>
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
          {activeTab === 'summarization' && (
            <>
              {/* Force Map-Reduce toggle */}
              <ForceMapReduceToggle
                value={appSettings.force_map_reduce === 'true'}
                onSaved={setAppSettings}
              />

              {/* Model selector — shared across both modes */}
              <div className="settings-section" style={{ paddingBottom: '0.75rem', borderBottom: '1px solid #eee', marginBottom: '1rem' }}>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label>Model <span className="required-mark">*</span></label>
                  <ModelOnlyPanel
                    stage="summarization"
                    initial={summarization}
                    models={models}
                    modelsOnline={modelsOnline}
                    onSaved={setSummarization}
                  />
                </div>
              </div>

              {/* Sub-tabs for prompts */}
              <div className="result-tabs" style={{ marginBottom: '1rem' }}>
                <button
                  className={`result-tab ${summSubTab === 'single_pass' ? 'active' : ''}`}
                  onClick={() => setSummSubTab('single_pass')}
                >
                  Single Pass
                </button>
                <button
                  className={`result-tab ${summSubTab === 'map_reduce' ? 'active' : ''}`}
                  onClick={() => setSummSubTab('map_reduce')}
                >
                  Map-Reduce
                </button>
              </div>

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
                <>
                  <div className="result-tabs" style={{ marginBottom: '1rem' }}>
                    <button
                      className={`result-tab ${mapReduceStep === 'extract' ? 'active' : ''}`}
                      onClick={() => setMapReduceStep('extract')}
                    >
                      Step 1 — Extract (per chunk)
                    </button>
                    <button
                      className={`result-tab ${mapReduceStep === 'combine' ? 'active' : ''}`}
                      onClick={() => setMapReduceStep('combine')}
                    >
                      Step 2 — Combine (all chunks)
                    </button>
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
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
