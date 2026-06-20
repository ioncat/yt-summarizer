import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getResult, getModels, startBenchmark, getBenchmarkRuns, deleteBenchmarkRun, BenchmarkRun, ResultResponse } from '../api'
import { renderText } from '../utils/renderText'

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function compressionLabel(input: number, output: number | null): string {
  if (!output) return ''
  const pct = Math.round((1 - output / input) * 100)
  if (pct > 0) return `${pct}% compressed`
  if (pct < 0) return `+${Math.abs(pct)}% expanded`
  return '0% change'
}

function modeBadge(mode: string): string {
  if (mode === 'full_extract') return 'Full Extract'
  if (mode === 'map_reduce')   return 'Map-Reduce'
  return 'Single-pass'
}

function formatChars(n: number | null): string {
  if (n == null) return '—'
  return n.toLocaleString('ru-RU') + ' chars'
}

const MODE_OPTIONS = [
  { value: '',             label: 'Auto-detect'  },
  { value: 'single',       label: 'Single-pass'  },
  { value: 'map_reduce',   label: 'Map-Reduce'   },
  { value: 'full_extract', label: 'Full Extract' },
]

export default function BenchmarkPage() {
  const { videoId } = useParams<{ videoId: string }>()
  const navigate    = useNavigate()

  const [video, setVideo]                   = useState<ResultResponse | null>(null)
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [selectedModels, setSelectedModels] = useState<string[]>([])
  const [modeOverride, setModeOverride]     = useState<string>('')
  const [stage, setStage]                   = useState<'summary' | 'cleanup'>('summary')
  const [runs, setRuns]                     = useState<BenchmarkRun[]>([])
  const [running, setRunning]               = useState(false)
  const [error, setError]                   = useState<string | null>(null)
  const [statsClosed, setStatsClosed]       = useState<Set<number>>(new Set())
  const pollRef     = useRef<ReturnType<typeof setInterval> | null>(null)
  const columnRefs  = useRef<(HTMLDivElement | null)[]>([])
  const syncingRef  = useRef(false)

  useEffect(() => {
    if (!videoId) return
    Promise.all([
      getResult(videoId).then(setVideo).catch(() => {}),
      getModels().then(setAvailableModels).catch(() => {}),
      getBenchmarkRuns(videoId).then(setRuns).catch(() => {}),
    ])
  }, [videoId])

  useEffect(() => {
    const pending = runs.some(r => r.status === 'processing' || r.status === 'queued')
    if (pending && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        if (!videoId) return
        const fresh = await getBenchmarkRuns(videoId).catch(() => runs)
        setRuns(fresh)
        const stillPending = fresh.some(r => r.status === 'processing' || r.status === 'queued')
        if (!stillPending) {
          clearInterval(pollRef.current!)
          pollRef.current = null
          setRunning(false)
        }
      }, 3000)
    }
    return () => {
      if (!pending && pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [runs, videoId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleDeleteRun(run: BenchmarkRun) {
    const confirmed = window.confirm(
      `Delete this benchmark run?\n\nModel: ${run.model}\nStage: ${run.stage}\nStatus: ${run.status}\n\nThis cannot be undone.`
    )
    if (!confirmed) return
    try {
      await deleteBenchmarkRun(run.id)
      setRuns(prev => prev.filter(r => r.id !== run.id))
    } catch (err: any) {
      setError(err.message ?? 'Failed to delete run')
    }
  }

  function toggleModel(model: string) {
    setSelectedModels(prev =>
      prev.includes(model) ? prev.filter(m => m !== model) : [...prev, model]
    )
  }

  function toggleStats(runId: number) {
    setStatsClosed(prev => {
      const next = new Set(prev)
      if (next.has(runId)) next.delete(runId)
      else next.add(runId)
      return next
    })
  }

  async function handleRun() {
    if (!videoId || selectedModels.length === 0) return
    setError(null)
    setRunning(true)
    try {
      await startBenchmark(videoId, selectedModels, modeOverride || null, stage)
      const fresh = await getBenchmarkRuns(videoId)
      setRuns(fresh)
    } catch (e: any) {
      setError(e.message ?? 'Failed to start benchmark')
      setRunning(false)
    }
  }

  function handleColumnScroll(idx: number) {
    if (syncingRef.current) return
    syncingRef.current = true
    const src = columnRefs.current[idx]
    if (!src) { syncingRef.current = false; return }
    columnRefs.current.forEach((col, i) => {
      if (i !== idx && col) col.scrollTop = src.scrollTop
    })
    syncingRef.current = false
  }

  function handleExportHtml() {
    if (!displayRuns.length) return
    const title    = video?.title ?? videoId ?? 'benchmark'
    const date     = new Date().toISOString().slice(0, 10)
    const safeName = title.replace(/[/\\:*?"<>|]/g, '_')
    const cols = displayRuns.map(run => `
      <div class="col">
        <div class="col-header">
          <strong>${run.model}</strong>
          <span class="badge">${modeBadge(run.mode)}</span>
          <span>${formatDuration(run.duration_seconds)}</span>
          ${run.output_chars ? `<span>${compressionLabel(run.input_chars, run.output_chars)}</span>` : ''}
        </div>
        <div class="col-body">${
          run.status === 'failed'     ? '<p class="error">❌ Failed</p>' :
          run.status === 'queued'     ? '<p class="processing">⏸ Queued</p>' :
          run.status === 'processing' ? '<p class="processing">⏳ Processing…</p>' :
          (run.output_text ?? '').split('\n\n').map(b => {
            if (b.startsWith('## ')) {
              const nl = b.indexOf('\n')
              if (nl === -1) return `<h3>${b.slice(3)}</h3>`
              const heading = b.slice(3, nl).trim()
              const body    = b.slice(nl + 1).trim()
              return `<h3>${heading}</h3>${body ? `<p>${body}</p>` : ''}`
            }
            return `<p>${b}</p>`
          }).join('')
        }</div>
      </div>`).join('')

    const html = `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Benchmark: ${safeName}</title>
<style>
body{font-family:sans-serif;margin:0;padding:16px;background:#f9fafb}
.grid{display:grid;grid-template-columns:repeat(${displayRuns.length},1fr);gap:16px}
.col{background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden}
.col-header{padding:12px;background:#f3f4f6;display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:14px}
.badge{background:#e0e7ff;color:#3730a3;padding:2px 8px;border-radius:12px;font-size:12px}
.col-body{padding:16px;font-size:14px;line-height:1.6}
h3{font-size:1.05rem;font-weight:700;margin:24px 0 8px}
p{margin:0 0 12px}
.error{color:#dc2626}.processing{color:#92400e}
</style></head>
<body>
<h1 style="font-size:18px;margin-bottom:4px">${title}</h1>
<p style="color:#6b7280;font-size:13px;margin-bottom:16px">Benchmark · ${date}</p>
<div class="grid">${cols}</div>
</body></html>`

    const blob = new Blob([html], { type: 'text/html' })
    const a    = document.createElement('a')
    a.href     = URL.createObjectURL(blob)
    a.download = `benchmark_${safeName}_${date}.html`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const displayRuns = (() => {
    const seen = new Set<string>()
    return [...runs]
      .filter(r => r.stage === stage)
      .sort((a, b) => b.id - a.id)
      .filter(r => {
        if (seen.has(r.model)) return false
        seen.add(r.model)
        return true
      }).reverse()
  })()

  const inputCls = `bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all`

  return (
    <div className="p-4 md:p-6 space-y-5 max-w-full">

      {/* Header */}
      <div className="flex items-center gap-4 flex-wrap">
        <button
          onClick={() => navigate(`/result/${videoId}`)}
          className="flex items-center gap-2 px-4 py-2 bg-surface-container-high text-on-surface-variant text-label-md rounded-lg hover:bg-surface-container-highest transition-colors active:scale-[0.98]"
        >
          <span className="material-symbols-outlined text-[18px]">arrow_back</span>
          Back to result
        </button>
        <div className="flex items-center gap-3 min-w-0">
          <span className="material-symbols-outlined text-primary text-[24px]">speed</span>
          <div className="min-w-0">
            <h2 className="text-headline-lg font-bold text-on-surface leading-tight">Benchmark</h2>
            {video?.title && (
              <p className="text-body-sm text-secondary truncate max-w-[500px]">{video.title}</p>
            )}
          </div>
        </div>
      </div>

      {/* Controls card */}
      <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm p-5 space-y-4">

        {/* Stage + Mode row */}
        <div className="flex flex-wrap gap-4 items-end">
          <div className="space-y-1.5">
            <label className="text-label-md text-on-surface block">Stage</label>
            <select
              value={stage}
              onChange={e => setStage(e.target.value as 'summary' | 'cleanup')}
              disabled={running}
              className={inputCls}
            >
              <option value="summary">Summary</option>
              <option value="cleanup">Cleanup</option>
            </select>
          </div>

          {stage === 'summary' && (
            <div className="space-y-1.5">
              <label className="text-label-md text-on-surface block">Mode</label>
              <select
                value={modeOverride}
                onChange={e => setModeOverride(e.target.value)}
                disabled={running}
                className={inputCls}
              >
                {MODE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          )}

          {/* Run + Export buttons */}
          <div className="flex gap-3 ml-auto items-end">
            {displayRuns.length > 0 && (
              <button
                onClick={handleExportHtml}
                className="flex items-center gap-2 px-4 py-2 bg-surface-container-high text-on-surface-variant text-label-md rounded-lg hover:bg-surface-container-highest transition-colors active:scale-[0.98]"
              >
                <span className="material-symbols-outlined text-[18px]">download</span>
                Export HTML
              </button>
            )}
            <button
              onClick={handleRun}
              disabled={running || selectedModels.length === 0}
              className="flex items-center gap-2 px-5 py-2 bg-primary text-on-primary text-label-md font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[18px]">
                {running ? 'pending' : 'play_arrow'}
              </span>
              {running ? 'Running…' : 'Run benchmark'}
            </button>
          </div>
        </div>

        {/* Model chips */}
        {availableModels.length > 0 && (
          <div className="space-y-1.5">
            <label className="text-label-md text-on-surface block">Models</label>
            <div className="flex flex-wrap gap-2">
              {availableModels.map(m => {
                const active = selectedModels.includes(m)
                return (
                  <button
                    key={m}
                    onClick={() => toggleModel(m)}
                    disabled={running}
                    className={`px-3 py-1.5 rounded-full border text-label-sm font-semibold transition-all active:scale-[0.97] disabled:opacity-50 ${
                      active
                        ? 'bg-primary-container/30 border-primary text-primary'
                        : 'border-outline-variant text-on-surface-variant hover:border-secondary hover:text-on-surface'
                    }`}
                  >
                    {m}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-start gap-3 p-4 bg-error-container/20 border border-error/30 rounded-lg">
          <span className="material-symbols-outlined text-error text-[18px] mt-0.5">warning</span>
          <p className="text-body-sm text-on-error-container">{error}</p>
        </div>
      )}

      {/* Empty state */}
      {displayRuns.length === 0 && !running && (
        <div className="py-12 text-center">
          <span className="material-symbols-outlined text-[48px] text-outline-variant block mb-3">compare</span>
          <p className="text-body-md text-secondary">
            Select models above and click "Run benchmark" to compare outputs side by side.
          </p>
        </div>
      )}

      {/* Results grid */}
      {displayRuns.length > 0 && (
        <div
          className="grid gap-4 overflow-x-auto pb-2"
          style={{ gridTemplateColumns: `repeat(${displayRuns.length}, minmax(320px, 1fr))` }}
        >
          {displayRuns.map((run, idx) => {
            const statsOpen   = !statsClosed.has(run.id)
            const compression = run.output_chars ? compressionLabel(run.input_chars, run.output_chars) : null

            return (
              <div key={run.id} className="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden flex flex-col min-w-0">

                {/* Column header */}
                <div className="px-4 py-3 bg-surface-container border-b border-outline-variant flex flex-wrap items-center gap-2">
                  <strong className="text-body-sm font-bold text-on-surface flex-1 min-w-0 truncate">
                    {run.model}
                  </strong>
                  {run.triggered_by === 'main' && (
                    <span className="px-2 py-0.5 bg-secondary-container text-on-secondary-container text-tag-uppercase font-bold rounded" title="From Result page (primary pipeline)">
                      Original
                    </span>
                  )}
                  <span className="px-2 py-0.5 bg-primary-container/20 text-primary text-tag-uppercase font-bold rounded">
                    {modeBadge(run.mode)}
                  </span>
                  {run.status === 'queued' && (
                    <span className="text-label-sm text-secondary">⏸ queued</span>
                  )}
                  {run.status === 'processing' && (
                    <span className="text-label-sm text-secondary pulse-dot">processing…</span>
                  )}
                  {run.status === 'failed' && (
                    <span className="text-label-sm text-error">failed</span>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDeleteRun(run)}
                    aria-label="Delete this run"
                    title="Delete this run"
                    className="material-symbols-outlined text-[18px] text-outline hover:text-error transition-colors ml-auto flex-shrink-0"
                  >
                    close
                  </button>
                </div>

                {/* Stats panel */}
                <div className="border-b border-outline-variant">
                  <button
                    onClick={() => toggleStats(run.id)}
                    className="w-full flex items-center gap-2 px-4 py-2 text-label-sm text-secondary hover:bg-surface-container-low transition-colors"
                  >
                    <span className="material-symbols-outlined text-[14px]">
                      {statsOpen ? 'expand_less' : 'expand_more'}
                    </span>
                    Stats
                  </button>
                  {statsOpen && (
                    <div className="px-4 pb-3 grid grid-cols-2 gap-x-4 gap-y-1">
                      {[
                        ['Duration',    formatDuration(run.duration_seconds)],
                        ['Input',       formatChars(run.input_chars)],
                        ['Output',      formatChars(run.output_chars ?? null)],
                        ...(compression ? [['Compression', compression]] : []),
                        ['Stage',       run.stage === 'summary' ? 'Summary' : 'Cleanup'],
                        ['Source',      run.triggered_by === 'main' ? 'Main pipeline' : 'Benchmark'],
                      ].map(([label, value]) => (
                        <div key={label} className="flex justify-between gap-2 py-0.5 col-span-1">
                          <span className="text-label-sm text-on-surface-variant">{label}</span>
                          <span className="text-label-sm text-on-surface font-medium text-right">{value}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Text body */}
                <div
                  className="flex-1 overflow-y-auto p-4 formatted-text"
                  style={{ maxHeight: '65vh', minHeight: '200px' }}
                  ref={el => { columnRefs.current[idx] = el }}
                  onScroll={() => handleColumnScroll(idx)}
                >
                  {run.status === 'failed' && (
                    <p className="text-error text-body-sm">Model failed or timed out.</p>
                  )}
                  {run.status === 'queued' && (
                    <p className="text-secondary text-body-sm">Waiting for previous runs to finish…</p>
                  )}
                  {run.status === 'processing' && (
                    <p className="text-secondary text-body-sm">Processing…</p>
                  )}
                  {run.status === 'done' && run.output_text && renderText(run.output_text)}
                </div>

              </div>
            )
          })}
        </div>
      )}

    </div>
  )
}
