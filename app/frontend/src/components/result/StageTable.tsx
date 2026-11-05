import { ResultResponse, StageName, StageRun, StageRunDetail } from '../../api'
import { formatDate, formatDuration } from './helpers'

const ORDER: StageName[] = ['extract', 'transcribe', 'cleanup', 'summary', 'mindmap']
const LABEL: Record<string, string> = {
  extract: 'Subtitles', transcribe: 'Speech-to-text', cleanup: 'Cleanup', summary: 'Summary', mindmap: 'Mind map',
}
const STATUS: Record<string, { text: string; cls: string }> = {
  processing: { text: 'running', cls: 'text-secondary' },
  done: { text: 'done', cls: 'text-tertiary' },
  failed: { text: 'failed', cls: 'text-error' },
  cancelled: { text: 'stopped', cls: 'text-on-surface-variant' },
}
// reason codes (services/stage_codes.py) in plain words
const REASON: Record<string, string> = {
  empty_answer: 'the model returned nothing',
  context_too_small: 'the answer was cut off: the context is too small',
  model_missing: 'no model or Ollama address is set',
  timeout: 'timed out',
  no_subtitles: 'no subtitles',
  ollama_down: 'Ollama is not reachable',
  cancelled: 'stopped',
  unexpected: 'unexpected error',
  no_text: 'no text to work on',
  not_found: 'the video is not in History',
  upstream_failed: 'an earlier step failed',
  no_speech: 'no speech was found in the file',
  file_missing: 'the uploaded file is no longer on disk',
}

function seconds(run: StageRunDetail): number | null {
  if (!run.started_at || !run.finished_at) return null
  const s = (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000
  return Number.isFinite(s) && s >= 0 ? Math.round(s) : null
}

function Row({ stage, run }: { stage: string; run: StageRun }) {
  const st = STATUS[run.status] ?? { text: run.status, cls: 'text-on-surface-variant' }
  const shown = run.last_done            // the run the saved result came from
  const made: StageRunDetail = shown ?? run
  const took = seconds(made)
  return (
    <tr className="border-t border-outline-variant/40 align-top">
      <td className="py-2 pr-4 font-medium text-on-surface">{LABEL[stage] ?? stage}</td>
      <td className={`py-2 pr-4 font-semibold ${st.cls}`}>{st.text}</td>
      <td className="py-2 pr-4 text-on-surface-variant">{(shown?.model ?? run.model) || '—'}</td>
      <td className="py-2 pr-4 text-on-surface-variant whitespace-nowrap">
        {made.finished_at ? formatDate(made.finished_at) : '—'}
        {took != null && <> · {formatDuration(took)}</>}
      </td>
      <td className="py-2 text-on-surface-variant">
        {run.status === 'processing' && run.progress_total != null && (
          <span>{typeof run.meta.unit === 'string' ? `${run.meta.unit} ` : ''}{run.progress_done ?? 0} / {run.progress_total}</span>
        )}
        {run.status === 'failed' && (
          <span className="text-error">
            {run.error_code ? (REASON[run.error_code] ?? run.error_code) : 'failed'}
            {run.error_text && <span className="block text-label-sm font-mono break-words opacity-80">{run.error_text}</span>}
          </span>
        )}
        {run.status === 'failed' && shown && <span className="block text-label-sm">Showing the earlier successful run{shown.model ? ` (${shown.model})` : ''}.</span>}
        {run.status === 'cancelled' && shown && <span>Showing the earlier successful run.</span>}
        {run.runs > 1 && <span className="block text-label-sm opacity-70">{run.runs} runs so far</span>}
      </td>
    </tr>
  )
}

export function StageTable({ result }: { result: ResultResponse }) {
  const stages = result.stages ?? {}
  const present = ORDER.flatMap((s): Array<[StageName, StageRun]> => { const run = stages[s]; return run ? [[s, run]] : [] })
  if (present.length === 0) return null
  const anyFailed = present.some(([, run]) => run.status === 'failed')
  return (
    <details open={anyFailed} className="px-6 py-3 border-t border-outline-variant text-body-sm">
      <summary className="cursor-pointer text-label-md font-semibold text-secondary select-none">
        Processing steps ({present.length}){anyFailed && <span className="text-error"> · something failed</span>}
      </summary>
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-left">
          <thead>
            <tr className="text-label-sm text-secondary">
              <th className="pb-1 pr-4 font-medium">Step</th>
              <th className="pb-1 pr-4 font-medium">Now</th>
              <th className="pb-1 pr-4 font-medium" title="The model of the saved result">Model</th>
              <th className="pb-1 pr-4 font-medium" title="When the saved result was made, and how long it took">Result made</th>
              <th className="pb-1 font-medium">Details</th>
            </tr>
          </thead>
          <tbody>{present.map(([s, run]) => <Row key={s} stage={s} run={run} />)}</tbody>
        </table>
      </div>
    </details>
  )
}
