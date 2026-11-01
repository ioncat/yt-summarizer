import { useEffect, useState } from 'react'
import { saveSettings, StageSettings } from '../../api'
import { SELECT, SavedToast } from './primitives'

export function ModelOnlyPanel({ stage, initial, models, modelsOnline, onSaved }: {
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
