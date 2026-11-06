import { Link } from 'react-router-dom'

export interface BulkAddResult {
  added: number
  invalid: string[]
  duplicates: string[]
}

/** What a list of links came to: how many were added, and the links that were skipped. */
export function BulkReport({ result }: { result: BulkAddResult }) {
  const skipped = [
    ...result.duplicates.map(u => ({ url: u, reason: 'duplicate' })),
    ...result.invalid.map(u => ({ url: u, reason: 'invalid' })),
  ]
  return (
    <div className="flex flex-col gap-2">
      {result.added > 0 && (
        <div className="bg-tertiary-container/20 border border-tertiary/30 rounded-lg px-4 py-3 flex items-center gap-2">
          <span className="material-symbols-outlined text-tertiary text-[18px]">check_circle</span>
          <span className="text-body-sm text-on-surface">
            Added <strong>{result.added}</strong> to queue.{' '}
            <Link to="/queue" className="font-semibold text-primary underline">View queue →</Link>
          </span>
        </div>
      )}
      {skipped.length > 0 && (
        <div className="bg-surface-container-high border border-outline-variant rounded-lg px-4 py-3">
          <p className="text-label-sm text-secondary mb-2">Skipped: {skipped.length}</p>
          <ul className="flex flex-col gap-1">
            {skipped.map(({ url, reason }, i) => (
              <li key={i} className="flex items-baseline gap-2 text-body-sm">
                <span className="font-mono text-on-surface-variant break-all opacity-80">{url}</span>
                <span className="text-secondary italic flex-shrink-0">{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
