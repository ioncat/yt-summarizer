import { useState } from 'react'
import { saveAppSettings, AppSettings } from '../../api'
import { Hint, SavedToast } from './primitives'

export function ForceMapReduceToggle({ value, onSaved }: { value: boolean; onSaved: (s: AppSettings) => void }) {
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
