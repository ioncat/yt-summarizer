import { useEffect, useState } from 'react'
import { getHealth, HealthResponse } from '../api'

type Status = 'checking' | 'ok' | 'error'

function StatusItem({ status, label, pulse }: { status: Status; label: string; pulse?: boolean }) {
  const dotClass =
    status === 'ok' ? 'bg-tertiary-container' :
    status === 'error' ? 'bg-error' :
    'bg-surface-container-highest'
  const textClass = status === 'ok' ? 'text-tertiary font-bold' : status === 'error' ? 'text-error font-bold' : 'text-secondary'
  const statusText = status === 'ok' ? 'Online' : status === 'error' ? 'Offline' : '…'
  return (
    <div className="flex items-center gap-2">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotClass} ${pulse ? 'pulse-dot' : ''}`} />
      <span className="text-label-sm text-on-surface">
        {label}: <span className={textClass}>{statusText}</span>
      </span>
    </div>
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

  const overall: Status = backend === 'ok' && ollama === 'ok' ? 'ok' : backend === 'error' || ollama === 'error' ? 'error' : 'checking'

  return (
    <div className="flex items-center gap-6">
      <StatusItem status={overall} label="Systems Health" pulse />
      <StatusItem status={backend} label="API Status" />
      <StatusItem status={ollama} label="Ollama Core" />
    </div>
  )
}
