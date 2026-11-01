import { useState } from 'react'
import { BOXED_LAYOUT_EVENT, BOXED_LAYOUT_KEY } from '../../App'
import { Hint } from './primitives'

export function BoxedLayoutToggle() {
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
