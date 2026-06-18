import { useEffect, useState } from 'react'
import { getHealth, HealthResponse } from '../api'

type Status = 'checking' | 'ok' | 'error'

function Dot({ status, label }: { status: Status; label: string }) {
  const color =
    status === 'ok' ? '#22c55e' :
    status === 'error' ? '#ef4444' :
    '#94a3b8'
  const title =
    status === 'ok' ? `${label} — online` :
    status === 'error' ? `${label} — offline` :
    `${label} — checking…`
  return (
    <span className="flex items-center gap-1.5 text-xs text-secondary" title={title}>
      <span className="w-2 h-2 rounded-full inline-block flex-shrink-0" style={{ background: color }} />
      {label}
    </span>
  )
}

export default function StatusBar() {
  const [backend, setBackend] = useState<Status>('checking')
  const [ollama, setOllama] = useState<Status>('checking')

  function check() {
    getHealth()
      .then((h: HealthResponse) => {
        setBackend(h.backend ? 'ok' : 'error')
        setOllama(h.ollama ? 'ok' : 'error')
      })
      .catch(() => {
        setBackend('error')
        setOllama('error')
      })
  }

  useEffect(() => {
    check()
    const id = setInterval(check, 15_000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs font-semibold text-secondary uppercase tracking-wider flex items-center gap-1.5">
        Systems Health
        <svg width="14" height="9" viewBox="0 0 24 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="0,6 4,6 6,4 8,6 10,6 12,0 14,12 16,6 18,6 20,4 22,6 24,6" />
        </svg>
      </span>
      <span className="text-outline-variant text-sm">·</span>
      <Dot status={backend} label="API" />
      <span className="text-outline-variant text-sm">·</span>
      <Dot status={ollama} label="Ollama" />
    </div>
  )
}
