import { useEffect, useRef, useState } from 'react'
import { saveAppSettings, getYtdlpVersion, getYtdlpLatestVersion, updateYtdlp, AppSettings } from '../../api'
import { INPUT, SELECT, Hint, WarnBanner, SavedToast } from './primitives'

interface GeneralPanelProps {
  initial: AppSettings
  onSaved: (s: AppSettings) => void
}

const CHAT_CTX_VALUES = ['4096', '8192', '16384', '32768', '65536', '131072']
const LLM_CTX_VALUES = ['4096', '8192', '16384', '32768', '65536']

/** A stored value that is not one of the listed sizes (typed into the database or an older version, say 7000) would show as the first
 *  option and look like a different setting. It gets its own line, "custom: 7000", and stays selected until another is picked. */
function customOption(stored: string | null | undefined, listed: string[]) {
  if (!stored || listed.includes(stored)) return null
  return <option value={stored}>custom: {stored}</option>
}

export function GeneralPanel({ initial, onSaved }: GeneralPanelProps) {
  const [ollamaUrl, setOllamaUrl]           = useState(initial.ollama_url ?? '')
  const [useCustomYtdlp, setUseCustomYtdlp] = useState(!!initial.ytdlp_path)
  const [ytdlpPath, setYtdlpPath]           = useState(initial.ytdlp_path ?? '')
  const [cookiesPath, setCookiesPath]       = useState(initial.cookies_path ?? '')
  const [parallelWorkers, setParallelWorkers] = useState(initial.parallel_workers ?? '1')
  const [parallelError, setParallelError]   = useState('')
  const [chatNumCtx, setChatNumCtx]         = useState(initial.chat_num_ctx ?? '32768')
  const [llmMaxNumCtx, setLlmMaxNumCtx]     = useState(initial.llm_max_num_ctx ?? '32768')
  const [downloadFormat, setDownloadFormat] = useState(initial.download_default_format ?? 'mp4')
  const [downloadQuality, setDownloadQuality] = useState(initial.download_default_quality ?? 'best')
  const [saving, setSaving]                 = useState(false)
  const [toast, setToast]                   = useState('')
  const [ytdlpVersion, setYtdlpVersion]     = useState<string | null>(null)
  const [ytdlpLatest, setYtdlpLatest]       = useState<string | null>(null)
  const [ytdlpUpdateStatus, setYtdlpUpdateStatus] = useState<string>('idle')
  const [ytdlpUpdateError, setYtdlpUpdateError]   = useState<string>('')
  const fileRef = useRef<HTMLInputElement>(null)
  const updatePollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    setOllamaUrl(initial.ollama_url ?? '')
    setUseCustomYtdlp(!!initial.ytdlp_path)
    setYtdlpPath(initial.ytdlp_path ?? '')
    setCookiesPath(initial.cookies_path ?? '')
    setParallelWorkers(initial.parallel_workers ?? '1')
    setChatNumCtx(initial.chat_num_ctx ?? '32768')
    setLlmMaxNumCtx(initial.llm_max_num_ctx ?? '32768')
    setDownloadFormat(initial.download_default_format ?? 'mp4')
    setDownloadQuality(initial.download_default_quality ?? 'best')
  }, [initial])

  useEffect(() => {
    getYtdlpVersion().then(r => {
      setYtdlpVersion(r.version)
      if (r.update_status === 'running') setYtdlpUpdateStatus('running')
    })
    getYtdlpLatestVersion().then(r => setYtdlpLatest(r.latest))
    return () => { if (updatePollRef.current) clearInterval(updatePollRef.current) }
  }, [])

  function showToast(msg: string) { setToast(msg); setTimeout(() => setToast(''), 2500) }

  async function handleSave() {
    const pw = parseInt(parallelWorkers, 10)
    if (isNaN(pw) || pw < 1 || pw > 16) {
      setParallelError('Must be an integer between 1 and 16')
      return
    }
    setParallelError('')
    setSaving(true)
    const start = Date.now()
    try {
      const saved = await saveAppSettings({
        ollama_url: ollamaUrl || null,
        ytdlp_path: useCustomYtdlp ? (ytdlpPath || null) : null,
        cookies_path: cookiesPath || null,
        parallel_workers: String(pw),
        chat_num_ctx: chatNumCtx,
        llm_max_num_ctx: llmMaxNumCtx,
        download_default_format: downloadFormat,
        download_default_quality: downloadQuality,
      })
      onSaved(saved)
      showToast('Saved')
    } catch {
      showToast('Failed to save')
    } finally {
      const elapsed = Date.now() - start
      const remaining = 500 - elapsed
      if (remaining > 0) await new Promise(r => setTimeout(r, remaining))
      setSaving(false)
    }
  }

  async function handleCookiesUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const text = await file.text()
    const formData = new FormData()
    formData.append('file', new Blob([text], { type: 'text/plain' }), file.name)
    try {
      const res = await fetch('/api/settings/upload-cookies', { method: 'POST', body: formData })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setCookiesPath(data.path)
      showToast('Cookies uploaded')
    } catch {
      showToast('Upload failed')
    }
    if (fileRef.current) fileRef.current.value = ''
  }

  async function handleUpdateYtdlp() {
    setYtdlpUpdateStatus('running')
    setYtdlpUpdateError('')
    try {
      await updateYtdlp()
      updatePollRef.current = setInterval(async () => {
        const r = await getYtdlpVersion()
        if (r.update_status === 'done') {
          if (updatePollRef.current) clearInterval(updatePollRef.current)
          setYtdlpUpdateStatus('done')
          if (r.new_version) setYtdlpVersion(r.new_version)
          showToast(`Updated to v${r.new_version ?? 'latest'}`)
        } else if (r.update_status === 'failed') {
          if (updatePollRef.current) clearInterval(updatePollRef.current)
          setYtdlpUpdateStatus('failed')
          setYtdlpUpdateError(r.update_error ?? 'pip failed')
        }
        // status === 'running' → keep polling
      }, 2000)
    } catch {
      setYtdlpUpdateStatus('failed')
      setYtdlpUpdateError('Could not reach backend')
    }
  }

  const missing = [
    !ollamaUrl  && 'Ollama URL',
    !cookiesPath && 'Cookies path',
  ].filter(Boolean)

  return (
    <div className="space-y-5">
      {missing.length > 0 && (
        <WarnBanner>Required fields missing: {missing.join(', ')}</WarnBanner>
      )}

      {/* Ollama URL */}
      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface flex items-center gap-1">
          Ollama URL <span className="text-error">*</span>
        </label>
        <input
          type="text"
          className={INPUT(!ollamaUrl)}
          value={ollamaUrl}
          onChange={e => setOllamaUrl(e.target.value)}
          placeholder="http://localhost:11434"
        />
      </div>

      {/* Chat context window */}
      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface">Chat context window (minimum)</label>
        <p className="text-body-sm text-on-surface-variant">
          The chat asks Ollama for at least this many tokens (transcript + conversation) and grows with the conversation up to the
          larger of this value and the limit below. Larger values use more VRAM.
        </p>
        <select
          className={SELECT()}
          value={chatNumCtx}
          onChange={e => setChatNumCtx(e.target.value)}
        >
          {customOption(initial.chat_num_ctx, CHAT_CTX_VALUES)}
          <option value="4096">4K — minimal (short clips only)</option>
          <option value="8192">8K</option>
          <option value="16384">16K</option>
          <option value="32768">32K — recommended</option>
          <option value="65536">64K — long videos</option>
          <option value="131072">128K — very long videos (high VRAM)</option>
        </select>
      </div>

      {/* Context limit of the other LLM steps */}
      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface" htmlFor="llm-max-num-ctx">Context limit for cleanup, summary and mind map</label>
        <p className="text-body-sm text-on-surface-variant">
          The app sizes the context to each input and never asks for more than this. Roughly 3 characters are 1 token and the answer
          needs room too: 8K takes about 20,000 characters of text (longer summaries go in pieces), 4K only about 6,000. Too small
          and a long video fails with "the answer would be cut off"; larger values use more VRAM.
        </p>
        <select
          id="llm-max-num-ctx"
          className={SELECT()}
          value={llmMaxNumCtx}
          onChange={e => setLlmMaxNumCtx(e.target.value)}
        >
          {customOption(initial.llm_max_num_ctx, LLM_CTX_VALUES)}
          <option value="4096">4K — tiny inputs only</option>
          <option value="8192">8K</option>
          <option value="16384">16K</option>
          <option value="32768">32K — recommended</option>
          <option value="65536">64K — long videos (high VRAM)</option>
        </select>
      </div>

      {/* yt-dlp section */}
      <div className="space-y-3 p-4 bg-surface-container-low rounded-xl border border-outline-variant">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-label-md text-on-surface font-medium">yt-dlp</p>
            <p className="text-[11px] text-on-surface-variant mt-0.5">
              {useCustomYtdlp ? 'Custom binary path' : 'Bundled (recommended)'}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {!useCustomYtdlp && (
              <div className="flex flex-col items-end gap-1.5">
                {/* Version info */}
                {ytdlpVersion ? (
                  <div className="flex flex-col items-end gap-0.5">
                    <span className="text-[11px] text-on-surface-variant">
                      installed: <span className="font-medium text-on-surface">v{ytdlpVersion}</span>
                    </span>
                    {ytdlpLatest && (
                      <span className={`text-[11px] ${ytdlpLatest !== ytdlpVersion ? 'text-primary font-medium' : 'text-on-surface-variant'}`}>
                        latest: v{ytdlpLatest}{ytdlpLatest === ytdlpVersion ? ' ✓' : ' ↑'}
                      </span>
                    )}
                  </div>
                ) : (
                  <span className="text-on-surface-variant/50 text-[11px]">version unknown</span>
                )}

                {/* Update button + status */}
                <div className="flex items-center gap-2">
                  {ytdlpUpdateStatus === 'running' && (
                    <span className="flex items-center gap-1.5 text-[11px] text-on-surface-variant">
                      <span className="inline-block w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                      Updating…
                    </span>
                  )}
                  {ytdlpUpdateStatus === 'done' && (
                    <span className="text-[11px] text-primary font-medium">✓ Updated</span>
                  )}
                  {ytdlpUpdateStatus === 'failed' && (
                    <span className="text-[11px] text-error font-medium" title={ytdlpUpdateError}>✕ Failed</span>
                  )}
                  <button
                    onClick={handleUpdateYtdlp}
                    disabled={ytdlpUpdateStatus === 'running'}
                    className="px-3 py-1 text-[11px] font-semibold rounded-lg bg-secondary-container text-on-secondary-container hover:opacity-90 active:scale-95 transition-all disabled:opacity-50"
                  >
                    {ytdlpUpdateStatus === 'running' ? '…' : ytdlpUpdateStatus === 'failed' ? 'Retry' : 'Update'}
                  </button>
                </div>

                {/* Error detail */}
                {ytdlpUpdateStatus === 'failed' && ytdlpUpdateError && (
                  <p className="text-[10px] text-error max-w-[200px] text-right leading-tight">{ytdlpUpdateError}</p>
                )}
              </div>
            )}
            {/* Toggle */}
            <button
              role="switch"
              aria-checked={useCustomYtdlp}
              onClick={() => setUseCustomYtdlp(v => !v)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${useCustomYtdlp ? 'bg-primary' : 'bg-surface-container-highest'}`}
            >
              <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${useCustomYtdlp ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
            <span className="text-[11px] text-on-surface-variant w-16">Custom path</span>
          </div>
        </div>
        {useCustomYtdlp && (
          <div className="space-y-1.5">
            <input
              type="text"
              className={INPUT(!ytdlpPath)}
              value={ytdlpPath}
              onChange={e => setYtdlpPath(e.target.value)}
              placeholder="C:/ytdlp/yt-dlp.exe"
            />
            <Hint>Absolute path to yt-dlp executable on the server.</Hint>
          </div>
        )}
      </div>

      {/* Cookies path with upload */}
      <div className="space-y-1.5">
        <label className="text-label-md text-on-surface flex items-center gap-1">
          Cookies path <span className="text-error">*</span>
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            className={INPUT(!cookiesPath) + ' flex-1'}
            value={cookiesPath}
            onChange={e => setCookiesPath(e.target.value)}
            placeholder="../data/www.youtube.com_cookies.txt"
          />
          <button
            onClick={() => fileRef.current?.click()}
            className="px-5 bg-surface-container-high text-on-surface text-label-md rounded-lg hover:bg-surface-dim transition-colors active:scale-95"
          >
            Upload
          </button>
        </div>
        <input ref={fileRef} type="file" accept=".txt" className="hidden" onChange={handleCookiesUpload} />
        <Hint>Export from Chrome via "Get cookies.txt LOCALLY" extension.</Hint>
      </div>

      {/* Parallel workers */}
      <div className="space-y-1.5 w-1/4 min-w-[140px]">
        <label className="text-label-md text-on-surface">Parallel workers</label>
        <input
          type="number"
          min={1}
          max={16}
          className={INPUT(!!parallelError)}
          value={parallelWorkers}
          onChange={e => { setParallelWorkers(e.target.value); setParallelError('') }}
        />
        {parallelError
          ? <p className="text-[11px] text-error mt-1">{parallelError}</p>
          : <Hint>Number of paragraphs/chunks processed simultaneously. Should match OLLAMA_NUM_PARALLEL.</Hint>
        }
      </div>

      {/* Download defaults */}
      <div className="space-y-3 p-4 bg-surface-container-low rounded-xl border border-outline-variant">
        <p className="text-label-md text-on-surface font-medium">Download defaults</p>
        <div className="flex gap-4 flex-wrap">
          <div className="space-y-1.5">
            <label className="text-[11px] text-on-surface-variant uppercase tracking-wide">Format</label>
            <select className={SELECT()} value={downloadFormat} onChange={e => setDownloadFormat(e.target.value)}>
              <option value="mp4">MP4 (video)</option>
              <option value="mp3">MP3 (audio only)</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] text-on-surface-variant uppercase tracking-wide">Quality</label>
            <select className={SELECT()} value={downloadQuality} onChange={e => setDownloadQuality(e.target.value)}>
              <option value="best">Best available</option>
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
              <option value="480p">480p</option>
            </select>
          </div>
        </div>
        <Hint>Applied when you click "Download" on the Result page (overridable per download).</Hint>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-4 pt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2.5 bg-primary text-on-primary text-label-md font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <SavedToast msg={toast} />
      </div>
    </div>
  )
}
