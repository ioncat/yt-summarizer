// The pipeline choice the Home page and the queue page's "New" button share.

export const PIPELINE_PRESETS = [
  { value: 'extract', label: 'Extract only', stages: ['extract'] },
  { value: 'cleanup', label: 'Extract + Cleanup', stages: ['extract', 'cleanup'] },
  { value: 'full', label: 'Full pipeline', stages: ['extract', 'cleanup', 'summary', 'mindmap'] },
]

export const AUTO_PIPELINE_KEY = 'yt_summarizer_auto_pipeline'

export function resolveStages(presetValue: string, useStt: boolean): string[] {
  const preset = PIPELINE_PRESETS.find(p => p.value === presetValue)
  const stages = preset?.stages ?? ['extract']
  if (useStt) return stages.map(s => s === 'extract' ? 'transcribe' : s)
  return stages
}

/** The Home page's "Run full pipeline" checkbox, as stored in the browser. */
export function readAutoPipeline(): boolean {
  try { return localStorage.getItem(AUTO_PIPELINE_KEY) === 'true' } catch { return false }
}

export function autoPipelineStages(useStt: boolean): string[] {
  return [useStt ? 'transcribe' : 'extract', 'cleanup', 'summary', 'mindmap']
}

/** What a link added without choosing anything gets: the full pipeline if the Home checkbox is on,
 *  otherwise what the Home page starts with (extract only). */
export function defaultQueueStages(useStt = false): string[] {
  return readAutoPipeline() ? autoPipelineStages(useStt) : resolveStages('extract', useStt)
}
