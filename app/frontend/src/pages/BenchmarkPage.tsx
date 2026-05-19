import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getResult, getModels, startBenchmark, getBenchmarkRuns, BenchmarkRun, ResultResponse } from '../api'
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

function modeBadge(mode: string, chunks?: number | null): string {
  if (mode === 'full_extract') return `Full Extract${chunks ? ` · ${chunks} ch` : ''}`
  if (mode === 'map_reduce') return `Map-Reduce`
  return 'Single-pass'
}

const MODE_OPTIONS = [
  { value: '', label: 'Auto-detect' },
  { value: 'single', label: 'Single-pass' },
  { value: 'map_reduce', label: 'Map-Reduce' },
  { value: 'full_extract', label: 'Full Extract' },
]

export default function BenchmarkPage() {
  const { videoId } = useParams<{ videoId: string }>()
  const navigate = useNavigate()

  const [video, setVideo] = useState<ResultResponse | null>(null)
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [selectedModels, setSelectedModels] = useState<string[]>([])
  const [modeOverride, setModeOverride] = useState<string>('')
  const [stage, setStage] = useState<'summary' | 'cleanup'>('summary')
  const [runs, setRuns] = useState<BenchmarkRun[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Synchronized scroll
  const columnRefs = useRef<(HTMLDivElement | null)[]>([])
  const syncingRef = useRef(false)

  useEffect(() => {
    if (!videoId) return
    Promise.all([
      getResult(videoId).then(setVideo).catch(() => {}),
      getModels().then(setAvailableModels).catch(() => {}),
      getBenchmarkRuns(videoId).then(setRuns).catch(() => {}),
    ])
  }, [videoId])

  // Poll while any run is processing
  useEffect(() => {
    const hasProcessing = runs.some(r => r.status === 'processing')
    if (hasProcessing && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        if (!videoId) return
        const fresh = await getBenchmarkRuns(videoId).catch(() => runs)
        setRuns(fresh)
        if (!fresh.some(r => r.status === 'processing')) {
          clearInterval(pollRef.current!)
          pollRef.current = null
          setRunning(false)
        }
      }, 3000)
    }
    return () => {
      if (!hasProcessing && pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [runs, videoId])

  function toggleModel(model: string) {
    setSelectedModels(prev =>
      prev.includes(model)
        ? prev.filter(m => m !== model)
        : prev.length < 4 ? [...prev, model] : prev
    )
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

  // Synchronized scroll handler
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
    const title = video?.title ?? videoId ?? 'benchmark'
    const date = new Date().toISOString().slice(0, 10)
    const safeTitle = title.replace(/[/\\:*?"<>|]/g, '_')
    const cols = displayRuns.map(run => `
      <div class="col">
        <div class="col-header">
          <strong>${run.model}</strong>
          <span class="badge">${modeBadge(run.mode)}</span>
          <span>${formatDuration(run.duration_seconds)}</span>
          ${run.output_chars ? `<span>${compressionLabel(run.input_chars, run.output_chars)}</span>` : ''}
        </div>
        <div class="col-body">${
          run.status === 'failed' ? '<p class="error">❌ Failed</p>' :
          run.status === 'processing' ? '<p class="processing">⏳ Processing…</p>' :
          (run.output_text ?? '').split('\n\n').map(b =>
            b.startsWith('## ')
              ? `<h3>${b.slice(3)}</h3>`
              : `<p>${b}</p>`
          ).join('')
        }</div>
      </div>`).join('')

    const html = `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Benchmark: ${safeTitle}</title>
<style>
body{font-family:sans-serif;margin:0;padding:16px;background:#f9fafb}
.grid{display:grid;grid-template-columns:repeat(${displayRuns.length},1fr);gap:16px}
.col{background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden}
.col-header{padding:12px;background:#f3f4f6;display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:14px}
.badge{background:#e0e7ff;color:#3730a3;padding:2px 8px;border-radius:12px;font-size:12px}
.col-body{padding:16px;font-size:14px;line-height:1.6}
h3{font-weight:600;border-bottom:2px solid #e0e7ff;padding-bottom:4px;margin:24px 0 8px}
p{margin:0 0 12px}
.error{color:#dc2626}.processing{color:#92400e}
</style></head>
<body>
<h1 style="font-size:18px;margin-bottom:4px">${title}</h1>
<p style="color:#6b7280;font-size:13px;margin-bottom:16px">Benchmark · ${date}</p>
<div class="grid">${cols}</div>
</body></html>`

    const blob = new Blob([html], { type: 'text/html' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `benchmark_${safeTitle}_${date}.html`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  // Filter by selected stage, then dedup by model (keep newest)
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

  const hasProcessing = runs.some(r => r.status === 'processing')

  return (
    <div className="benchmark-page">
      <div className="benchmark-header">
        <button className="btn-secondary" onClick={() => navigate(`/result/${videoId}`)}>
          ← Back to result
        </button>
        <div className="benchmark-title">
          <h2>Benchmark</h2>
          {video?.title && <span className="benchmark-video-title">{video.title}</span>}
        </div>
      </div>

      {/* Controls */}
      <div className="benchmark-controls">
        <div className="benchmark-mode-selector">
          <label>Stage:</label>
          <select
            value={stage}
            onChange={e => setStage(e.target.value as 'summary' | 'cleanup')}
            disabled={running}
          >
            <option value="summary">Summary</option>
            <option value="cleanup">Cleanup</option>
          </select>
        </div>
        <div className="benchmark-model-selector">
          <label>Models (select up to 4):</label>
          <div className="model-chips">
            {availableModels.map(m => (
              <button
                key={m}
                className={`model-chip ${selectedModels.includes(m) ? 'active' : ''}`}
                onClick={() => toggleModel(m)}
                disabled={running}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        {stage === 'summary' && (
          <div className="benchmark-mode-selector">
            <label>Mode:</label>
            <select
              value={modeOverride}
              onChange={e => setModeOverride(e.target.value)}
              disabled={running}
            >
              {MODE_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        )}

        <button
          className="btn-primary"
          onClick={handleRun}
          disabled={running || selectedModels.length === 0}
        >
          {running ? '⏳ Running…' : '▶ Run benchmark'}
        </button>

        {displayRuns.length > 0 && (
          <button className="btn-secondary" onClick={handleExportHtml}>
            ↓ Export HTML
          </button>
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Results grid */}
      {displayRuns.length > 0 && (
        <div
          className="benchmark-grid"
          style={{ gridTemplateColumns: `repeat(${displayRuns.length}, 1fr)` }}
        >
          {displayRuns.map((run, idx) => (
            <div key={run.id} className="benchmark-col">
              <div className="benchmark-col-header">
                <strong className="benchmark-model-name">{run.model}</strong>
                {run.triggered_by === 'main' && (
                  <span className="benchmark-badge benchmark-badge-original" title="From Result page (primary pipeline)">📌 Original</span>
                )}
                <span className="benchmark-badge">{modeBadge(run.mode)}</span>
                {run.status === 'done' && (
                  <>
                    <span className="benchmark-meta">{formatDuration(run.duration_seconds)}</span>
                    {run.output_chars && (
                      <span className="benchmark-meta">
                        {compressionLabel(run.input_chars, run.output_chars)}
                      </span>
                    )}
                  </>
                )}
                {run.status === 'processing' && (
                  <span className="benchmark-meta processing">⏳ processing…</span>
                )}
                {run.status === 'failed' && (
                  <span className="benchmark-meta failed">❌ failed</span>
                )}
              </div>
              <div
                className="benchmark-col-body formatted-text"
                ref={el => { columnRefs.current[idx] = el }}
                onScroll={() => handleColumnScroll(idx)}
              >
                {run.status === 'failed' && (
                  <p className="benchmark-error">Model failed or timed out.</p>
                )}
                {run.status === 'processing' && (
                  <p className="benchmark-processing">Processing…</p>
                )}
                {run.status === 'done' && run.output_text && renderText(run.output_text)}
              </div>
            </div>
          ))}
        </div>
      )}

      {displayRuns.length === 0 && !running && (
        <div className="benchmark-empty">
          Select models above and click "Run benchmark" to compare outputs side by side.
        </div>
      )}
    </div>
  )
}
