import { useEffect, useState } from 'react'
import { saveSettings, resetSettings, StageSettings } from '../../api'
import { SELECT, TEXTAREA, Hint, WarnBanner, SavedToast } from './primitives'

interface StagePanelProps {
  stage: string
  initial: StageSettings
  models: string[]
  modelsOnline: boolean
  hideModel?: boolean
}

export function StagePanel({ stage, initial, models, modelsOnline, hideModel }: StagePanelProps) {
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
