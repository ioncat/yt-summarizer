import type { ResultResponse } from '../../api'
import type { Tab } from './helpers'

/** What the "Added to queue" line on the result page is about (NS-17 item 2). */
export type QueuedMsg = 'cleanup' | 'summary' | 'mindmap' | 'cleanup+summary'

const STAGES: Record<QueuedMsg, Array<'cleanup' | 'summary' | 'mindmap'>> = {
  cleanup: ['cleanup'],
  summary: ['summary'],
  mindmap: ['mindmap'],
  'cleanup+summary': ['cleanup', 'summary'],
}

/** The tabs where the line belongs: the tab of the work that was queued (a summary line does not follow you to the Subtitles tab). */
const TABS: Record<QueuedMsg, Tab[]> = {
  cleanup: ['cleaned'],
  summary: ['summary'],
  mindmap: ['mindmap'],
  'cleanup+summary': ['cleaned', 'summary'],
}

export function queuedStagesRunning(msg: QueuedMsg, result: ResultResponse | null): boolean {
  if (!result) return false
  return STAGES[msg].some(s => result[`${s}_status`] === 'processing')
}

/** The line is shown while the queued work is still waiting or running, and only on the tab it belongs to. */
export function queuedLineVisible(msg: string | null, tab: Tab, result: ResultResponse | null): boolean {
  if (!msg || !(msg in STAGES)) return false
  const m = msg as QueuedMsg
  return TABS[m].includes(tab) && queuedStagesRunning(m, result)
}

/** The page's copy of the result right after a click that queued work: the endpoint sets these stages to "processing" at once,
 *  so the page says so too instead of waiting for its next poll (which is what let the line outlive the work). */
export function withQueuedProcessing(prev: ResultResponse, stages: Array<'cleanup' | 'summary' | 'mindmap'>): ResultResponse {
  const next = { ...prev }
  for (const s of stages) next[`${s}_status`] = 'processing'
  return next
}
