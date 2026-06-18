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
    <span className="flex items-center gap-2">
      Queue
      {active > 0 && (
        <span className="bg-primary text-on-primary text-xs font-semibold rounded-full px-1.5 py-0.5 leading-none min-w-[18px] text-center">
          {active}
        </span>
      )}
    </span>
  )
}
