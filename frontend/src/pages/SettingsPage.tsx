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
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setOllamaUrl(initial.ollama_url ?? '')
    setYtdlpPath(initial.ytdlp_path ?? '')
    setCookiesPath(initial.cookies_path ?? '')
  }, [initial])

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(''), 2500)
  }

  async function handleSave() {
    setSaving(true)
    try {
      const saved = await saveAppSettings({
        ollama_url: ollamaUrl || null,
        ytdlp_path: ytdlpPath || null,
        cookies_path: cookiesPath || null,
      })
      onSaved(saved)
      showToast('Saved')
    } catch {
      showToast('Failed to save')
    } finally {
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
      if (!res.ok) throw new Error()
      const data = await res.json()
      setCookiesPath(data.path)
      showToast('Cookies uploaded')
    } catch {
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
// AI stage tab (cleanup / summarization)
// ---------------------------------------------------------------------------

interface StagePanelProps {
  stage: string
  initial: StageSettings
  models: string[]
  modelsOnline: boolean
  locked?: boolean
}

function StagePanel({ stage, initial, models, modelsOnline, locked }: StagePanelProps) {
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

  const missingModel = !locked && !model

  return (
    <div className="settings-section">
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

const TABS: { id: TabId; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'cleanup', label: 'AI Cleanup' },
  { id: 'summarization', label: 'Summarization' },
]

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<TabId>('general')
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null)
  const [cleanup, setCleanup] = useState<StageSettings | null>(null)
  const [summarization, setSummarization] = useState<StageSettings | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [modelsOnline, setModelsOnline] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getSettings()
      .then(s => {
        setAppSettings(s.app)
        setCleanup(s.cleanup)
        setSummarization(s.summarization)
      })
      .catch(() => setError('Could not load settings'))

    getModels()
      .then(list => { setModels(list); setModelsOnline(true) })
      .catch(() => setModelsOnline(false))
  }, [])

  if (error) return (
    <div className="container">
      <div className="card"><div className="error-box">{error}</div></div>
    </div>
  )

  if (!appSettings || !cleanup || !summarization) return (
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
          {activeTab === 'cleanup' && cleanup && (
            <StagePanel
              stage="cleanup"
              initial={cleanup}
              models={models}
              modelsOnline={modelsOnline}
            />
          )}
          {activeTab === 'summarization' && summarization && (
            <StagePanel
              stage="summarization"
              initial={summarization}
              models={models}
              modelsOnline={modelsOnline}
              locked
            />
          )}
        </div>
      </div>
    </div>
  )
}
