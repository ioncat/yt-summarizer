import type { ResultResponse } from '../../api'
import { btnSecondary } from './helpers'

/** The jobs of this video that are waiting or running, whatever the stage and whatever tab is open (NS-16). */
export function activeJobs(result: ResultResponse): string[] {
  const jobs: string[] = []
  if (result.reextract_in_progress) jobs.push('re-extract')
  if (result.cleanup_status === 'processing') jobs.push('AI cleanup')
  if (result.summary_status === 'processing') jobs.push('summary')
  if (result.mindmap_status === 'processing') jobs.push('mind map')
  return jobs
}

/** One Cancel for everything that is waiting or running for the video: a waiting job leaves the queue, a running one stops;
 *  what each step had saved before stays. Shown only while there is something to stop. */
export function JobsBanner({ result, handleStopAll }: { result: ResultResponse; handleStopAll: () => void }) {
  const jobs = activeJobs(result)
  if (jobs.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-outline-variant bg-secondary-container/10 px-4 py-2" role="status">
      <span className="material-symbols-outlined text-[18px] text-secondary pulse-dot">hourglass_top</span>
      <span className="text-body-sm text-on-surface">In progress: {jobs.join(', ')}</span>
      <button
        onClick={handleStopAll}
        className={`${btnSecondary} ml-auto`}
        title="Waiting jobs leave the queue, running ones stop. Saved results stay."
      >
        <span className="material-symbols-outlined text-[18px]">cancel</span>Cancel all jobs
      </button>
    </div>
  )
}
