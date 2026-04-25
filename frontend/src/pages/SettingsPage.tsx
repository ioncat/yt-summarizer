import { useEffect, useState } from 'react'
import { getSettings, saveSettings, resetSettings, getModels, StageSettings } from '../api'

const STAGE_LABELS: Record<string, string> = {
  cleanup: 'AI Cleanup',
  summarization: 'Summarization',
}

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
      showToast('Settings saved')
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

  return (
    <div className={`card settings-panel${locked ? ' settings-panel-locked' : ''}`}>
      <div className="settings-panel-header">
        <h2>{STAGE_LABELS[stage] ?? stage}</h2>
        {locked && <span className="phase-badge">Phase 2 — coming soon</span>}
      </div>

      <div className="form-group">
        <label>Model</label>
        <select
          value={model}
          onChange={e => setModel(e.target.value)}
          disabled={locked || !modelsOnline}
          title={!modelsOnline ? 'Ollama offline — cannot load models' : undefined}
        >
          <option value="">Default ({'{OLLAMA_MODEL}'})</option>
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

export default function SettingsPage() {
  const [settings, setSettings] = useState<{ cleanup: StageSettings; summarization: StageSettings } | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [modelsOnline, setModelsOnline] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch(() => setError('Could not load settings'))

    getModels()
      .then(list => {
        setModels(list)
        setModelsOnline(true)
      })
      .catch(() => setModelsOnline(false))
  }, [])

  if (error) return (
    <div className="container">
      <div className="card"><div className="error-box">{error}</div></div>
    </div>
  )

  if (!settings) return (
    <div className="container">
      <div className="card"><div className="status-box"><div className="spinner" /></div></div>
    </div>
  )

  return (
    <div className="container">
      <h1>Settings</h1>
      <p className="subtitle">Configure prompts and models for each pipeline stage.</p>
      <StagePanel
        stage="cleanup"
        initial={settings.cleanup}
        models={models}
        modelsOnline={modelsOnline}
      />
      <StagePanel
        stage="summarization"
        initial={settings.summarization}
        models={models}
        modelsOnline={modelsOnline}
        locked
      />
    </div>
  )
}
