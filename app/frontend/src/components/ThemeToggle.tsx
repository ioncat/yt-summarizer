import { useEffect, useState } from 'react'
import { Theme, getInitialTheme, saveTheme } from '../utils/theme'

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme())

  useEffect(() => {
    saveTheme(theme)
  }, [theme])

  function toggle() {
    setTheme(t => (t === 'light' ? 'dark' : 'light'))
  }

  const label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
  const icon = theme === 'dark' ? '☀' : '☾'

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={label}
      title={label}
    >
      {icon}
    </button>
  )
}
