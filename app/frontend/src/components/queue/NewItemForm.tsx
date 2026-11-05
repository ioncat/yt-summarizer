import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AddOutcome, AddRow, Settled } from './useQueueAdd'

function shortLink(url: string) {
  return url.length > 70 ? url.slice(0, 67) + '…' : url
}

/** One link, the default pipeline (the Home page's choice), Enter adds it; the page stays where it is.
 *  Enter takes the text out of the field at once and sends it as its own "Adding..." row, so links typed in quick
 *  succession are all sent and a finishing request never wipes what has been typed since. */
export default function NewItemForm({ add, rows, settled, isAdding, onRetry, onDismiss, onClose }: {
  add: (url: string) => Promise<AddOutcome | null>
  rows: AddRow[]
  settled: Settled | null
  isAdding: (url: string) => boolean
  onRetry: (id: number) => void
  onDismiss: (id: number) => void
  onClose: () => void
}) {
  const [url, setUrl] = useState('')
  const busy = rows.some(r => r.state === 'adding')
  const sameLinkBusy = isAdding(url.trim())  // this very link has an "Adding..." row: Add and Enter do nothing

  // A link that turned out to be queued / added / processed (also after a Retry) leaves no copy in the field.
  useEffect(() => {
    if (settled && settled.outcome.kind !== 'invalid') setUrl(cur => (cur.trim() === settled.url ? '' : cur))
  }, [settled])

  async function submit(e: FormEvent) {
    e.preventDefault()
    const link = url.trim()
    if (!link || isAdding(link)) return
    setUrl('')                                    // the link now lives in its own row; the field is free for the next one
    const result = await add(link)
    // a link that is not a link comes back to the field for editing, unless something new was typed meanwhile
    if (result?.kind === 'invalid') setUrl(cur => (cur === '' ? link : cur))
  }

  const outcome = settled?.outcome ?? null

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
        <button type="submit" disabled={!url.trim() || sameLinkBusy}
          className="px-4 py-2 bg-primary text-on-primary rounded-lg text-label-md font-semibold disabled:opacity-50">
          {busy ? 'Adding…' : 'Add'}
        </button>
        <button type="button" onClick={onClose}
          className="px-3 py-2 text-secondary rounded-lg text-label-md hover:bg-surface-container-high">
          Close
        </button>
      </div>
      {outcome && outcome.kind !== 'error' && (
        <p className={`text-body-sm ${outcome.kind === 'added' ? 'text-tertiary' : outcome.kind === 'invalid' ? 'text-error' : 'text-on-surface'}`} role="status">
          {outcome.kind === 'added' && 'Added to the queue.'}
          {outcome.kind === 'in_queue' && 'Already in the queue.'}
          {outcome.kind === 'invalid' && 'Not a YouTube link.'}
          {outcome.kind === 'processed' && (
            <>Already processed. <Link className="font-semibold text-primary underline" to={`/result/${outcome.videoId}`}>Open the result</Link></>
          )}
        </p>
      )}
      {rows.length > 0 && (
        <ul className="flex flex-col gap-1" aria-label="Links being added">
          {rows.map(r => (
            <li key={r.id} data-testid="adding-row" className="flex items-center gap-3 text-body-sm flex-wrap">
              <span className="material-symbols-outlined text-[18px] text-secondary">{r.state === 'adding' ? 'sync' : 'error'}</span>
              <span className="font-mono text-on-surface-variant" title={r.url}>{shortLink(r.url)}</span>
              {r.state === 'adding' && <span className="text-secondary">Adding…</span>}
              {r.state === 'failed' && (
                <>
                  {/* no answer: the server may have added it, so do not claim it was not */}
                  <span className="text-error" role="alert">{r.uncertain ? r.error : `Not added: ${r.error}`}</span>
                  <button type="button" onClick={() => onRetry(r.id)} className="font-semibold text-primary underline">Retry</button>
                  <button type="button" onClick={() => onDismiss(r.id)} className="text-secondary underline">Dismiss</button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </form>
  )
}
