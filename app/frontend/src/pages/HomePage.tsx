import { useState, useEffect, FormEvent, useRef } from 'react'
import { Link } from 'react-router-dom'
import { FileUploadForm } from '../components/home/FileUploadForm'
import { BulkReport, reportOf } from '../components/home/BulkReport'
import type { QueueReportEntry } from '../api'
import { parseLinks } from '../utils/links'
import { LANGUAGES, inputBase, selectBase } from '../components/home/common'
import { AUTO_PIPELINE_KEY, PIPELINE_PRESETS, autoPipelineStages, readAutoPipeline, resolveStages } from '../utils/pipeline'
import { getSettings, getHealth, getQueue, AllSettings, queueBulkAdd, QueueAddResult, downloadDirect } from '../api'

type InputMode = 'url' | 'file'

export default function HomePage() {
  const [inputMode, setInputMode] = useState<InputMode>('url')
  const [url, setUrl] = useState('')
  const [language, setLanguage] = useState('auto')
  const [pipeline, setPipeline] = useState('extract')
  const [useStt, setUseStt] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [queueNote, setQueueNote] = useState<
    { kind: 'added' | 'in_queue' | 'invalid' } | { kind: 'processed' | 'done'; videoId: string | null }
    | { kind: 'failed'; reason: string } | null>(null)
  // The queue item the "Added to the queue" note follows: the note turns into "Done" / "Failed" when the item ends (no jump)
  const [watchedItem, setWatchedItem] = useState<number | null>(null)
  const watchedRef = useRef<number | null>(null)
  const [missingConfig, setMissingConfig] = useState<string[]>([])
  const [allSettings, setAllSettings] = useState<AllSettings | null>(null)
  const [autoPipeline, setAutoPipeline] = useState(readAutoPipeline)
  const [autoDownload, setAutoDownload] = useState(
    () => localStorage.getItem('yt_autoDownload_enabled') === 'true'
  )
  const [autoDownloadFormat, setAutoDownloadFormat] = useState<'mp4' | 'mp3'>(
    () => (localStorage.getItem('yt_autoDownload_format') as 'mp4' | 'mp3') ?? 'mp4'
  )
  const [autoDownloadQuality, setAutoDownloadQuality] = useState(
    () => localStorage.getItem('yt_autoDownload_quality') ?? 'best'
  )
  const [ollamaOnline, setOllamaOnline] = useState(false)

  // The report of a list (two or more links): what was added and why each other link was skipped
  const [bulkResult, setBulkResult] = useState<{ added: number; report: QueueReportEntry[] } | null>(null)

  // The page stays: a line says what happened, so the next link can be pasted at once.
  // A duplicate carries its video id from the server (links like /live/, youtu.be/ and /shorts/ have no ?v=)
  function afterQueueAdd(res: QueueAddResult) {
    const dup = res.duplicate_details?.[0]
    if (dup?.reason === 'processed') setQueueNote({ kind: 'processed', videoId: dup.video_id })
    else if (dup) setQueueNote({ kind: 'in_queue' })
    else if (res.added > 0) { setQueueNote({ kind: 'added' }); setUrl(''); if (res.ids?.length === 1) setWatchedItem(res.ids[0]) }
    else setQueueNote({ kind: 'invalid' })
  }

  // One link: the line above ("Added" / "Already processed" ...) and the follow of its queue item. Two or more: the report of the list.
  function afterAdd(res: QueueAddResult) {
    if (links.length === 1) { afterQueueAdd(res); return }
    setBulkResult({ added: res.added, report: reportOf(res) })
    if (res.added > 0) setUrl('')
  }

  // Follow the queued item: one request at a time, an answer that arrives after the watch ended or changed is ignored, and the
  // poll stops with the page.
  useEffect(() => {
    watchedRef.current = watchedItem
    if (watchedItem == null) return
    let busy = false
    const id = setInterval(async () => {
      if (busy) return
      busy = true
      try {
        const data = await getQueue()
        if (watchedRef.current !== watchedItem) return                      // stale answer
        const item = data.items.find(i => i.id === watchedItem)
        if (!item) { setWatchedItem(null); return }                         // taken out of the queue: nothing more to say
        if (item.status === 'done') {
          setQueueNote({ kind: 'done', videoId: item.video_id })
          setWatchedItem(null)
        } else if (item.status === 'failed' || item.status === 'partial' || item.status === 'skipped') {
          setQueueNote({ kind: 'failed', reason: item.error_message || (item.status === 'skipped' ? 'Stopped' : 'no reason was recorded') })
          setWatchedItem(null)
        }
      } catch {
        // the next tick asks again
      } finally {
        busy = false
      }
    }, 3000)
    return () => { clearInterval(id); watchedRef.current = null }
  }, [watchedItem])

  const links = parseLinks(url)         // one per line; a lone link and a list go the same way

  useEffect(() => {
    Promise.all([getSettings(), getHealth()])
      .then(([s, health]) => {
        const missing: string[] = []
        if (!s.app.cookies_path) missing.push('Cookies')
        setMissingConfig(missing)
        setAllSettings(s)
        setOllamaOnline(health.ollama)
      })
      .catch(err => { console.error('[Home] getSettings failed:', err) })
  }, [])

  function storeAutoDownloadIntent() {
    if (autoDownload) {
      localStorage.setItem('yt_autoDownload', JSON.stringify({ format: autoDownloadFormat, quality: autoDownloadQuality }))
    } else {
      localStorage.removeItem('yt_autoDownload')
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    return submitLink()
  }

  async function submitLink() {
    setError('')
    setQueueNote(null)
    setWatchedItem(null)
    setBulkResult(null)
    if (links.length === 0) return

    if (autoDownload && !autoPipeline && pipeline === 'extract') {
      if (links.length > 1) { setError('Download works for one link at a time: leave one link in the field.'); return }
      setLoading(true)
      try {
        await downloadDirect(links[0], autoDownloadFormat, autoDownloadQuality)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Download failed')
      } finally {
        setLoading(false)
      }
      return
    }

    if (autoPipeline) {
      if (allSettings) {
        const issues: string[] = []
        if (!allSettings.app.ollama_url) issues.push('Ollama URL not configured (Settings → General)')
        if (!allSettings.cleanup.model) issues.push('AI Cleanup model not selected (Settings → AI Cleanup)')
        if (!allSettings.summarization.model) issues.push('Summarization model not selected (Settings → Summarization)')
        if (issues.length) {
          setError('Auto-pipeline is not ready:\n• ' + issues.join('\n• '))
          return
        }
      }
      setLoading(true)
      storeAutoDownloadIntent()
      try {
        afterAdd(await queueBulkAdd(links, autoPipelineStages(useStt), false, language || undefined))
      } catch (err) {
        console.error('[Home] queueBulkAdd failed:', err)
        setError(err instanceof Error ? err.message : 'Failed to add to queue')
      } finally {
        setLoading(false)
      }
    } else {
      // Every pipeline, "extract only" too, is a queue item (NS-11 stage 7 / NS-24b): the page stays and says what happened. A link
      // that is already processed shows the "already processed" note with a link to the result instead of jumping there.
      const stages = resolveStages(pipeline, useStt)
      setLoading(true)
      storeAutoDownloadIntent()
      try {
        afterAdd(await queueBulkAdd(links, stages, false, language || undefined))
      } catch (err) {
        console.error('[Home] queueBulkAdd failed:', err)
        setError(err instanceof Error ? err.message : 'Failed to add to queue')
      } finally {
        setLoading(false)
      }
    }
  }

  return (
    <div className="flex-grow flex flex-col items-center justify-start p-6 md:p-12 max-w-[1200px] mx-auto w-full gap-8 pt-8">

      {/* Missing config warning */}
      {missingConfig.length > 0 && (
        <div className="w-full max-w-2xl bg-error-container border border-error/30 rounded-xl px-5 py-3 flex items-center gap-3">
          <span className="material-symbols-outlined text-error text-[20px]">warning</span>
          <span className="text-body-sm text-on-error-container">
            Required settings missing: <strong>{missingConfig.join(', ')}</strong>.{' '}
            <Link to="/settings" className="font-semibold underline">Go to Settings →</Link>
          </span>
        </div>
      )}

      {/* Main form card */}
      <div className="w-full max-w-2xl bg-surface-container-lowest border border-outline-variant rounded-xl p-8 shadow-sm">
        <div className="text-center mb-8">
          <h2 className="text-headline-xl font-bold text-on-surface mb-2">YT Summarizer</h2>
          <p className="text-body-md text-secondary">Extract, clean, and summarize video content.</p>
        </div>

        {/* Mode tabs */}
        <div className="flex gap-1 bg-surface-container-low rounded-lg p-1 mb-6">
          {(['url', 'file'] as InputMode[]).map(mode => (
            <button
              key={mode}
              type="button"
              onClick={() => { setInputMode(mode); setError('') }}
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-md text-label-md font-medium transition-all cursor-pointer ${inputMode === mode ? 'bg-surface-container-highest text-on-surface shadow-sm' : 'text-on-surface-variant hover:text-on-surface'}`}
            >
              <span className="material-symbols-outlined text-[18px]">{mode === 'url' ? 'link' : 'upload_file'}</span>
              {mode === 'url' ? 'YouTube URL' : 'Local File'}
            </button>
          ))}
        </div>

        {/* URL form */}
        {inputMode === 'url' && (
          <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
            <div className="flex flex-col gap-2">
              <label className="text-label-md text-on-surface-variant font-medium" htmlFor="url">
                YouTube links <span className="text-secondary font-normal">(one per line; Enter adds a single link)</span>
              </label>
              <textarea
                id="url"
                className={inputBase + ' font-mono text-body-sm resize-y'}
                placeholder="https://www.youtube.com/watch?v=..."
                rows={3}
                value={url}
                onChange={e => { setUrl(e.target.value); setBulkResult(null) }}
                onKeyDown={e => {
                  // Enter on a single link adds it (the quick one-by-one add); with several lines Enter is a new line,
                  // and Ctrl / Cmd + Enter adds the list
                  if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return
                  if (links.length <= 1 || e.ctrlKey || e.metaKey) { e.preventDefault(); if (!loading && links.length) void submitLink() }
                }}
                required
                autoFocus
              />
              {links.length > 1 && <span className="text-label-sm text-secondary">{links.length} links detected</span>}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex flex-col gap-2">
                <label className="text-label-md text-on-surface-variant font-medium" htmlFor="pipeline">Pipeline</label>
                <div className="relative">
                  <select id="pipeline" className={selectBase} value={pipeline} onChange={e => setPipeline(e.target.value)} disabled={autoPipeline}>
                    {PIPELINE_PRESETS.map(p => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                  <span className="material-symbols-outlined pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-secondary text-[20px]">expand_more</span>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-label-md text-on-surface-variant font-medium" htmlFor="lang">Language</label>
                <div className="relative">
                  <select id="lang" className={selectBase} value={language} onChange={e => setLanguage(e.target.value)}>
                    {LANGUAGES.map(l => (
                      <option key={l.value} value={l.value}>{l.label}</option>
                    ))}
                  </select>
                  <span className="material-symbols-outlined pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-secondary text-[20px]">expand_more</span>
                </div>
              </div>
            </div>

            {/* STT toggle */}
            <div className="flex items-center gap-3 pt-1">
              <input
                id="use-stt"
                type="checkbox"
                className="w-5 h-5 rounded border-outline-variant cursor-pointer accent-primary"
                checked={useStt}
                onChange={e => setUseStt(e.target.checked)}
              />
              <label htmlFor="use-stt" className="text-label-md text-on-surface cursor-pointer">
                Use speech-to-text (Whisper) instead of captions
              </label>
            </div>

            {/* Auto-pipeline checkbox */}
            <div className="flex items-center gap-3">
              <input
                id="auto-pipeline"
                type="checkbox"
                className="w-5 h-5 rounded border-outline-variant cursor-pointer accent-primary"
                checked={autoPipeline}
                disabled={!ollamaOnline}
                onChange={e => {
                  setAutoPipeline(e.target.checked)
                  localStorage.setItem(AUTO_PIPELINE_KEY, String(e.target.checked))
                }}
              />
              <label htmlFor="auto-pipeline" className={`text-label-md text-on-surface cursor-pointer ${!ollamaOnline ? 'opacity-50' : ''}`}>
                Run full pipeline (Transcript + Cleanup + Summary)
                {!ollamaOnline && <span className="ml-2 text-secondary font-normal">— Ollama offline</span>}
              </label>
            </div>

            {/* Auto-download checkbox */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-3">
                <input
                  id="auto-download"
                  type="checkbox"
                  className="w-5 h-5 rounded border-outline-variant cursor-pointer accent-primary shrink-0"
                  checked={autoDownload}
                  onChange={e => {
                    setAutoDownload(e.target.checked)
                    localStorage.setItem('yt_autoDownload_enabled', String(e.target.checked))
                  }}
                />
                <label htmlFor="auto-download" className="text-label-md text-on-surface cursor-pointer">
                  Download
                  <span className="text-secondary font-normal"> (auto-starts after processing)</span>
                </label>
              </div>
              {autoDownload && (
                <div className="flex items-center gap-3 ml-8">
                  <div className="relative shrink-0 w-36">
                    <select
                      value={autoDownloadFormat}
                      onChange={e => {
                        const v = e.target.value as 'mp4' | 'mp3'
                        setAutoDownloadFormat(v)
                        localStorage.setItem('yt_autoDownload_format', v)
                      }}
                      className={selectBase}
                    >
                      <option value="mp4">Video (MP4)</option>
                      <option value="mp3">Audio (MP3)</option>
                    </select>
                    <span className="material-symbols-outlined pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-secondary text-[20px]">expand_more</span>
                  </div>
                  <div className="relative shrink-0 w-44">
                    <select
                      value={autoDownloadQuality}
                      onChange={e => {
                        setAutoDownloadQuality(e.target.value)
                        localStorage.setItem('yt_autoDownload_quality', e.target.value)
                      }}
                      className={selectBase}
                    >
                      <option value="best">Best quality</option>
                      <option value="1080p">1080p</option>
                      <option value="720p">720p</option>
                      <option value="480p">480p</option>
                    </select>
                    <span className="material-symbols-outlined pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-secondary text-[20px]">expand_more</span>
                  </div>
                </div>
              )}
            </div>

            {queueNote && (
              <div role="status" className="bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3 text-body-sm text-on-surface">
                {queueNote.kind === 'added' && <>Added to the queue. <Link to="/queue" className="font-semibold text-primary underline">View queue →</Link></>}
                {queueNote.kind === 'in_queue' && <>Already in the queue. <Link to="/queue" className="font-semibold text-primary underline">View queue →</Link></>}
                {queueNote.kind === 'processed' && <>Already processed. <Link to={`/result/${queueNote.videoId}`} className="font-semibold text-primary underline">Open the result →</Link></>}
                {queueNote.kind === 'done' && <>Done. {queueNote.videoId
                  ? <Link to={`/result/${queueNote.videoId}`} className="font-semibold text-primary underline">Open the result →</Link>
                  : <Link to="/queue" className="font-semibold text-primary underline">View queue →</Link>}</>}
                {queueNote.kind === 'failed' && <><span className="text-error">Failed: {queueNote.reason}</span> <Link to="/queue" className="font-semibold text-primary underline">View queue →</Link></>}
                {queueNote.kind === 'invalid' && <span className="text-error">Not a YouTube link.</span>}
              </div>
            )}

            {bulkResult && <BulkReport added={bulkResult.added} report={bulkResult.report} />}

            {error && (
              <div role="alert" className="bg-error-container border border-error/30 rounded-lg px-4 py-3 flex items-center gap-3 flex-wrap">
                <p className="text-body-sm text-on-error-container whitespace-pre-line flex-1">{error}</p>
                {links.length > 0 && !loading && (
                  <button type="button" onClick={() => void submitLink()}
                    className="px-3 py-1 rounded-lg border border-error text-error text-label-sm font-semibold hover:bg-error hover:text-on-error">
                    Retry
                  </button>
                )}
              </div>
            )}

            <div className="flex flex-col md:flex-row gap-4 pt-4">
              <button
                type="submit"
                disabled={loading || links.length === 0}
                className="flex-grow bg-primary text-on-primary py-4 px-6 rounded-lg text-label-md font-bold transition-all hover:opacity-90 active:scale-[0.98] shadow-sm disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                {loading ? 'Adding…' : links.length > 1 ? `Add all (${links.length})` : 'Add to queue'}
              </button>
            </div>
          </form>
        )}

        {/* File upload form */}
        {inputMode === 'file' && <FileUploadForm />}
      </div>
    </div>
  )
}
