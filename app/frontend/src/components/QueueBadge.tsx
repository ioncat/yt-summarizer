import { useState, useEffect } from 'react'
import { getQueueCounts } from '../api'

export default function QueueBadge() {
  const [active, setActive] = useState(0)

  useEffect(() => {
    let mounted = true

    async function check() {
      try {
        const c = await getQueueCounts()
        if (mounted) setActive(c.active)
      } catch { /* ignore */ }
    }

    check()
    const interval = setInterval(check, 4000)
    return () => { mounted = false; clearInterval(interval) }
  }, [])

  return (
    <span className="queue-nav-link">
      ⏱ Queue
      {active > 0 && <span className="queue-badge">{active}</span>}
    </span>
  )
}
