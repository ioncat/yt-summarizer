import type { ResultResponse } from '../../api'
import { btnAi, btnSecondary } from './helpers'

/** Shown after "Summarize" on a video with no cleanup: a summary of the cleaned text is better, so ask what to do. It sits in the
 *  page, not in a browser dialog, so it cannot be blocked or dismissed without a trace (NS-17 item 18). */
export function CleanupFirstPrompt({ result, onCleanupThenSummarize, onSummarizeAnyway, onCancel }: {
  result: ResultResponse
  onCleanupThenSummarize: () => void
  onSummarizeAnyway: () => void
  onCancel: () => void
}) {
  if (result.cleanup_status || result.cleaned_text) return null       // a cleanup exists or is running: nothing to ask
  return (
    <div role="alertdialog" aria-label="AI cleanup has not been run yet"
         className="flex flex-wrap items-center gap-3 rounded-lg border border-outline-variant bg-secondary-container/10 px-4 py-3">
      <span className="material-symbols-outlined text-[20px] text-secondary">help</span>
      <span className="text-body-sm text-on-surface flex-1 min-w-[16rem]">
        AI cleanup has not been run on this video yet. A summary of the cleaned text is better.
      </span>
      <button onClick={onCleanupThenSummarize} className={btnAi}>Run cleanup, then summarize</button>
      <button onClick={onSummarizeAnyway} className={btnSecondary}>Summarize anyway</button>
      <button onClick={onCancel} className={btnSecondary}>Cancel</button>
    </div>
  )
}
