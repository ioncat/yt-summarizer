import { FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'
import { queueBulkAdd, QueueAddResult } from '../../api'
import { defaultQueueStages } from '../../utils/pipeline'

type Outcome =
  | { kind: 'added' }
  | { kind: 'processed'; videoId: string }
  | { kind: 'in_queue' }
  | { kind: 'invalid' }
  | { kind: 'error'; message: string }

function outcomeOf(res: QueueAddResult): Outcome {
  if (res.added > 0) return { kind: 'added' }
  const dup = res.duplicate_details?.[0]
  if (dup) return dup.reason === 'processed' ? { kind: 'processed', videoId: dup.video_id } : { kind: 'in_queue' }
  return { kind: 'invalid' }
}

/** One link, the default pipeline from Settings, Enter adds it; the page stays where it is. */
export default function NewItemForm({ onAdded, onClose }: { onAdded: () => void; onClose: () => void }) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const link = url.trim()
    if (!link || busy) return
    setBusy(true)
    try {
      // the same choice as the Home page (its "full pipeline" checkbox, else extract only)
      const res = await queueBulkAdd([link], defaultQueueStages(), false)
      const o = outcomeOf(res)
      setOutcome(o)
      if (o.kind === 'added') { setUrl(''); onAdded() }
    } catch (err) {
      setOutcome({ kind: 'error', message: err instanceof Error ? err.message : 'Failed to add to queue' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="px-6 py-4 border-b border-outline-variant bg-surface-container-low flex flex-col gap-2">
      <div className="flex gap-3 items-center">
        <input
          autoFocus
          type="text"
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="Paste a YouTube link and press Enter"
          aria-label="New video link"
          className="flex-1 px-4 py-2 bg-surface-container-lowest border border-outline-variant rounded-lg text-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
        />
        <button type="submit" disabled={busy || !url.trim()}
          className="px-4 py-2 bg-primary text-on-primary rounded-lg text-label-md font-semibold disabled:opacity-50">
          {busy ? 'Adding…' : 'Add'}
        </button>
        <button type="button" onClick={onClose}
          className="px-3 py-2 text-secondary rounded-lg text-label-md hover:bg-surface-container-high">
          Close
        </button>
      </div>
      {outcome && (
        <p className={`text-body-sm ${outcome.kind === 'added' ? 'text-tertiary' : outcome.kind === 'error' || outcome.kind === 'invalid' ? 'text-error' : 'text-on-surface'}`} role="status">
          {outcome.kind === 'added' && 'Added to the queue.'}
          {outcome.kind === 'in_queue' && 'Already in the queue.'}
          {outcome.kind === 'invalid' && 'Not a YouTube link.'}
          {outcome.kind === 'error' && outcome.message}
          {outcome.kind === 'processed' && (
            <>Already processed. <Link className="font-semibold text-primary underline" to={`/result/${outcome.videoId}`}>Open the result</Link></>
          )}
        </p>
      )}
    </form>
  )
}
