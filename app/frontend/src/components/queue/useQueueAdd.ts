import { useRef, useState } from 'react'
import { queueBulkAdd, QueueAddResult } from '../../api'
import { defaultQueueStages } from '../../utils/pipeline'

export type AddOutcome =
  | { kind: 'added' }
  | { kind: 'processed'; videoId: string }
  | { kind: 'in_queue' }
  | { kind: 'invalid' }
  | { kind: 'error'; message: string }

/** A link that has been sent and is not in the table yet: "Adding..." while the request runs, "Not added" if it failed. */
export interface AddRow {
  id: number
  url: string
  state: 'adding' | 'failed'
  error?: string
}

export function outcomeOf(res: QueueAddResult): AddOutcome {
  if (res.added > 0) return { kind: 'added' }
  const dup = res.duplicate_details?.[0]
  if (dup) return dup.reason === 'processed' ? { kind: 'processed', videoId: dup.video_id } : { kind: 'in_queue' }
  return { kind: 'invalid' }
}

/** Adding links from the queue page: an immediate "Adding..." row, a clear error with Retry (NS-28). */
export function useQueueAdd(onAdded: () => void) {
  const [rows, setRows] = useState<AddRow[]>([])
  const nextId = useRef(1)
  // links with a request on its way: a second Enter / click for the same link must not send a second request
  const sending = useRef(new Set<string>())

  function patch(id: number, change: Partial<AddRow>) {
    setRows(prev => prev.map(r => (r.id === id ? { ...r, ...change } : r)))
  }

  async function run(id: number, url: string): Promise<AddOutcome | null> {
    if (sending.current.has(url)) return null
    sending.current.add(url)
    patch(id, { state: 'adding', error: undefined })
    try {
      const res = await queueBulkAdd([url], defaultQueueStages(), false)
      const outcome = outcomeOf(res)
      setRows(prev => prev.filter(r => r.id !== id))  // it is in the table now, or the line under the field says why not
      if (outcome.kind === 'added') onAdded()
      return outcome
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to add to queue'
      patch(id, { state: 'failed', error: message })
      return { kind: 'error', message }
    } finally {
      sending.current.delete(url)
    }
  }

  /** null: this link is already being sent, nothing was done. */
  function add(url: string): Promise<AddOutcome | null> {
    if (sending.current.has(url)) return Promise.resolve(null)
    const id = nextId.current++
    setRows(prev => [...prev, { id, url, state: 'adding' }])
    return run(id, url)
  }

  function retry(id: number) {
    const row = rows.find(r => r.id === id)
    if (row && row.state === 'failed') void run(id, row.url)
  }

  function dismiss(id: number) {
    setRows(prev => prev.filter(r => r.id !== id))
  }

  const isAdding = (url: string) => rows.some(r => r.state === 'adding' && r.url === url)

  return { rows, add, retry, dismiss, isAdding }
}
