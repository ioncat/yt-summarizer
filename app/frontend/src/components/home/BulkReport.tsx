import { Link } from 'react-router-dom'
import type { QueueAddResult, QueueReportEntry } from '../../api'

export type ReportStatus = QueueReportEntry['status']

/** What the user reads for each status. "added" is the only one that put something in the queue. */
export const STATUS_TEXT: Record<ReportStatus, string> = {
  added: 'added to the queue',
  processed: 'already processed',
  in_queue: 'already in the queue',
  in_list: 'duplicate in the list',
  invalid: 'not a YouTube link',
}

/** One row per link in the order sent. The server sends it as `report`; for an older answer it is rebuilt from the other keys
 *  (the order is then: skipped links only, as that answer cannot say more). */
export function reportOf(res: QueueAddResult): QueueReportEntry[] {
  if (res.report) return res.report
  const details = res.duplicate_details ?? []
  return [
    ...(res.duplicates ?? []).map(url => {
      const d = details.find(x => x.url === url)
      const reason = d?.reason === 'processed' ? 'processed' : d?.reason === 'in_list' ? 'in_list' : 'in_queue'
      return { url, video_id: d?.video_id ?? null, status: reason } as QueueReportEntry
    }),
    ...res.invalid.map(url => ({ url, video_id: null, status: 'invalid' } as QueueReportEntry)),
  ]
}

/** What a list of links came to: a line with the counts, then every link with its own status. */
export function BulkReport({ added, report }: { added: number; report: QueueReportEntry[] }) {
  const skipped = report.filter(e => e.status !== 'added').length
  return (
    <div className="flex flex-col gap-2" data-testid="bulk-report">
      <div className="bg-surface-container-high border border-outline-variant rounded-lg px-4 py-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="material-symbols-outlined text-[18px] text-tertiary">{added > 0 ? 'check_circle' : 'info'}</span>
        <span className="text-body-sm text-on-surface">
          {added > 0 ? <>Added <strong>{added}</strong> to the queue</> : <>Nothing was added</>}
          {skipped > 0 && <>, skipped <strong>{skipped}</strong></>}.
        </span>
        {added > 0 && <Link to="/queue" className="text-body-sm font-semibold text-primary underline">View queue →</Link>}
      </div>
      {report.length > 0 && (
        <ul className="max-h-72 overflow-auto flex flex-col gap-1 border border-outline-variant rounded-lg px-4 py-3 bg-surface-container-low">
          {report.map((e, i) => (
            <li key={i} className="flex items-baseline gap-2 text-body-sm" data-status={e.status}>
              <span className={`material-symbols-outlined text-[16px] shrink-0 self-center ${e.status === 'added' ? 'text-tertiary' : 'text-secondary'}`}>
                {e.status === 'added' ? 'check' : 'remove'}
              </span>
              <span className="font-mono text-on-surface-variant break-all opacity-90">{e.url}</span>
              <span className={`italic shrink-0 ${e.status === 'added' ? 'text-tertiary' : e.status === 'invalid' ? 'text-error' : 'text-secondary'}`}>
                {STATUS_TEXT[e.status]}
              </span>
              {e.status === 'processed' && e.video_id && (
                <Link to={`/result/${e.video_id}`} className="shrink-0 font-semibold text-primary underline">Open the result →</Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
