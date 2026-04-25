import { useEffect, useState } from 'react'
import { getHealth, HealthResponse } from '../api'

type Status = 'checking' | 'ok' | 'error'

function Dot({ status, label }: { status: Status; label: string }) {
  const color = status === 'ok' ? '#22c55e' : status === 'error' ? '#ef4444' : '#94a3b8'
  const title =
    status === 'ok' ? `${label} — online` :
    status === 'error' ? `${label} — offline` :
    `${label} — checking…`
  return (
    <span className="status-dot-group" title={title}>
      <span className="status-dot" style={{ background: color }} />
      <span className="status-dot-label">{label}</span>
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
    <div className="status-bar">
      <Dot status={backend} label="API" />
      <Dot status={ollama} label="Ollama" />
    </div>
  )
}
