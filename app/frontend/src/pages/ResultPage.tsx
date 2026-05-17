import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getResult, deleteResult,
  startCleanup, cancelCleanup,
  startSummary, cancelSummary,
  getSettings, getModels, saveSettings,
  ResultResponse,
} from '../api'

type Tab = 'subtitles' | 'cleaned' | 'summary'

function formatDuration(seconds: number | null): string {
  if (seconds === 0) return '0:00'
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function ResultPage() {
  const { videoId } = useParams<{ videoId: string }>()
  const navigate = useNavigate()
  const [result, setResult] = useState<ResultResponse | null>(null)
  const [error, setError] = useState('')
  const [cleanupError, setCleanupError] = useState('')
  const [summaryError, setSummaryError] = useState('')
  const [copied, setCopied] = useState(false)
  const [activeTab, setActiveTab] = useState<Tab>('subtitles')
  const [cleanupModel, setCleanupModel] = useState('')
  const [summaryModel, setSummaryModel] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [cleanupElapsedSeconds, setCleanupElapsedSeconds] = useState<number | null>(null)
  const [summaryElapsedSeconds, setSummaryElapsedSeconds] = useState<number | null>(null)
  const [localCleanupDuration, setLocalCleanupDuration] = useState<number | null>(null)
  const [localSummaryDuration, setLocalSummaryDuration] = useState<number | null>(null)

  // Chat state
  const [ollamaUrl, setOllamaUrl] = useState('')
  const [chatHistory, setChatHistory] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([])
  const [chatInput, setChatInput] = useState('')
  const [isChatting, setIsChatting] = useState(false)
  const [chatCopied, setChatCopied] = useState(false)
  const ollamaMessagesRef = useRef<Array<{ role: string; content: string }>>([])
  const chatEndRef = useRef<HTMLDivElement>(null)
  const chatInputRef = useRef<HTMLTextAreaElement>(null)
  const CHAT_WARN_CHARS = 100_000

  // ── Notifications ──────────────────────────────────────────────────────────
  const originalTitleRef = useRef(document.title)

  function requestNotifyPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }

  function notify(title: string, body?: string) {
    // Tab title
    document.title = `✓ ${title}`
    setTimeout(() => { document.title = originalTitleRef.current }, 10_000)

    // Browser notification (only when tab is hidden)
    if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
      new Notification(title, { body, icon: '/favicon.ico' })
    }
  }
  // ───────────────────────────────────────────────────────────────────────────

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const summaryPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cleanupTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const summaryTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cleanupElapsedRef = useRef<number | null>(null)
  const summaryElapsedRef = useRef<number | null>(null)
  const prevCleanupStatusRef = useRef<string | null | undefined>(undefined)
  const prevSummaryStatusRef = useRef<string | null | undefined>(undefined)
  const cleanupPromptsRef = useRef<{ system_prompt: string | null; user_prompt_template: string | null }>({
    system_prompt: null, user_prompt_template: null,
  })
  const summaryPromptsRef = useRef<{ system_prompt: string | null; user_prompt_template: string | null }>({
    system_prompt: null, user_prompt_template: null,
  })

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }
  function stopSummaryPolling() {
    if (summaryPollRef.current) { clearInterval(summaryPollRef.current); summaryPollRef.current = null }
  }
  function stopCleanupTimer() {
    if (cleanupTimerRef.current) { clearInterval(cleanupTimerRef.current); cleanupTimerRef.current = null }
  }
  function stopSummaryTimer() {
    if (summaryTimerRef.current) { clearInterval(summaryTimerRef.current); summaryTimerRef.current = null }
  }
  function startCleanupTimer() {
    stopCleanupTimer()
    const startedAt = Date.now()
    setCleanupElapsedSeconds(0)
    cleanupElapsedRef.current = 0
    cleanupTimerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000)
      cleanupElapsedRef.current = elapsed
      setCleanupElapsedSeconds(elapsed)
    }, 1000)
  }
  function startSummaryTimer() {
    stopSummaryTimer()
    const startedAt = Date.now()
    setSummaryElapsedSeconds(0)
    summaryElapsedRef.current = 0
    summaryTimerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000)
      summaryElapsedRef.current = elapsed
      setSummaryElapsedSeconds(elapsed)
    }, 1000)
  }

  function loadResult(switchTab = false) {
    if (!videoId) return
    getResult(videoId)
      .then(data => {
        const prevCleanup = prevCleanupStatusRef.current
        const prevSummary = prevSummaryStatusRef.current
        prevCleanupStatusRef.current = data.cleanup_status
        prevSummaryStatusRef.current = data.summary_status
        setResult(data)

        // Tab auto-switching on initial load
        if (switchTab) {
          if (data.summary_status === 'done') setActiveTab('summary')
          else if (data.cleanup_status === 'done') setActiveTab('cleaned')
          else setActiveTab('subtitles')
        } else {
          if (prevCleanup === 'processing' && data.cleanup_status === 'done') {
            setActiveTab('cleaned')
            notify('AI Cleanup complete', data.title ?? undefined)
          }
          if (prevSummary === 'processing' && data.summary_status === 'done') {
            setActiveTab('summary')
            notify('Summary complete', data.title ?? undefined)
          }
        }

        // Cleanup polling/timer management
        if (data.cleanup_status !== 'processing') {
          if (prevCleanup === 'processing' && data.cleanup_status === 'done' && data.cleanup_duration_seconds == null) {
            setLocalCleanupDuration(cleanupElapsedRef.current)
          } else if (data.cleanup_duration_seconds != null) {
            setLocalCleanupDuration(null)
          }
          stopPolling()
          stopCleanupTimer()
          setCleanupElapsedSeconds(null)
        } else if (!cleanupTimerRef.current) {
          startCleanupTimer()
        }

        // Summary polling/timer management
        if (data.summary_status !== 'processing') {
          if (prevSummary === 'processing' && data.summary_status === 'done' && data.summary_duration_seconds == null) {
            setLocalSummaryDuration(summaryElapsedRef.current)
          } else if (data.summary_duration_seconds != null) {
            setLocalSummaryDuration(null)
          }
          stopSummaryPolling()
          stopSummaryTimer()
          setSummaryElapsedSeconds(null)
        } else if (!summaryTimerRef.current) {
          startSummaryTimer()
        }
      })
      .catch(err => { console.error('[Result] getResult failed:', err); setError('Could not load result') })
  }

  useEffect(() => {
    loadResult(true)
    return () => {
      stopPolling()
      stopSummaryPolling()
      stopCleanupTimer()
      stopSummaryTimer()
    }
  }, [videoId])

  function loadSettings() {
    Promise.all([getSettings(), getModels()])
      .then(([s, list]) => {
        setCleanupModel(s.cleanup.model ?? '')
        setSummaryModel(s.summarization.model ?? '')
        setOllamaUrl(s.app.ollama_url ?? '')
        setModels(list)
        cleanupPromptsRef.current = {
          system_prompt: s.cleanup.system_prompt ?? null,
          user_prompt_template: s.cleanup.user_prompt_template ?? null,
        }
        summaryPromptsRef.current = {
          system_prompt: s.summarization.system_prompt ?? null,
          user_prompt_template: s.summarization.user_prompt_template ?? null,
        }
      })
      .catch(err => console.error('[Result] failed to load model settings:', err))
  }

  useEffect(() => {
    originalTitleRef.current = document.title
    return () => { document.title = originalTitleRef.current }
  }, [])

  useEffect(() => {
    loadSettings()
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        loadSettings()
        // Restore title when user returns to tab
        document.title = originalTitleRef.current
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [])

  useEffect(() => {
    if (result?.cleanup_status === 'processing' && !pollRef.current) {
      pollRef.current = setInterval(() => loadResult(false), 3000)
    }
  }, [result?.cleanup_status])

  useEffect(() => {
    if (result?.summary_status === 'processing' && !summaryPollRef.current) {
      summaryPollRef.current = setInterval(() => loadResult(false), 3000)
    }
  }, [result?.summary_status])

  // Reset chat when summary is re-generated
  useEffect(() => {
    setChatHistory([])
    ollamaMessagesRef.current = []
  }, [result?.summary_text])

  // Auto-scroll to bottom after each chat message
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatHistory])

  async function sendChatMessage() {
    const question = chatInput.trim()
    if (!question || isChatting || !ollamaUrl || !summaryModel || !result) return

    // Build initial hidden context on first message
    if (ollamaMessagesRef.current.length === 0) {
      const sourceText = result.cleaned_text ?? result.formatted_text ?? ''
      const systemPrompt = summaryPromptsRef.current.system_prompt
      ollamaMessagesRef.current = [
        ...(systemPrompt ? [{ role: 'system', content: systemPrompt }] : []),
        { role: 'user', content: sourceText },
        { role: 'assistant', content: result.summary_text ?? '' },
      ]
    }

    ollamaMessagesRef.current = [...ollamaMessagesRef.current, { role: 'user', content: question }]
    setChatHistory(prev => [...prev, { role: 'user', content: question }, { role: 'assistant', content: '' }])
    setChatInput('')
    setIsChatting(true)

    let fullResponse = ''
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: summaryModel, messages: ollamaMessagesRef.current }),
      })
      if (!response.ok) throw new Error(`Ollama error ${response.status}`)

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const processLine = (line: string) => {
        if (!line.trim()) return
        try {
          const json = JSON.parse(line)
          const token = json.message?.content ?? json.response ?? ''
          if (token) {
            fullResponse += token
            setChatHistory(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = { role: 'assistant', content: fullResponse }
              return updated
            })
          }
        } catch { /* skip malformed lines */ }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) { if (buffer.trim()) processLine(buffer); break }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()!
        lines.forEach(processLine)
      }

      ollamaMessagesRef.current = [...ollamaMessagesRef.current, { role: 'assistant', content: fullResponse }]
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setChatHistory(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = { role: 'assistant', content: `⚠ ${msg}` }
        return updated
      })
    } finally {
      setIsChatting(false)
      chatInputRef.current?.focus()
    }
  }

  function copyChat() {
    if (!result || chatHistory.length === 0) return
    const lines = [
      `Video: ${result.title ?? ''}`,
      `\nSummary:\n${result.summary_text ?? ''}`,
      ...chatHistory.map(m => `\n${m.role === 'user' ? 'Q' : 'A'}: ${m.content}`),
    ].join('\n')
    navigator.clipboard.writeText(lines).then(() => {
      setChatCopied(true)
      setTimeout(() => setChatCopied(false), 2000)
    })
  }

  const displayText =
    activeTab === 'summary' ? result?.summary_text :
    activeTab === 'cleaned' ? (result?.cleaned_text ?? result?.formatted_text) :
    result?.formatted_text

  function renderText(text: string) {
    const blocks = text.split('\n\n')
    return blocks.map((block, i) => {
      if (block.startsWith('## ')) {
        return <h3 key={i} className="chapter-heading">{block.slice(3)}</h3>
      }
      return <p key={i} className="text-paragraph">{block}</p>
    })
  }

  async function handleCopy() {
    if (!displayText) return
    await navigator.clipboard.writeText(displayText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  async function handleCancelCleanup() {
    if (!videoId) return
    stopPolling(); stopCleanupTimer()
    try { await cancelCleanup(videoId) }
    catch (err) { console.error('[Result] cancelCleanup failed:', err) }
    setCleanupElapsedSeconds(null); cleanupElapsedRef.current = null; setLocalCleanupDuration(null)
    setResult(prev => prev ? { ...prev, cleanup_status: null, cleaned_text: null, cleanup_duration_seconds: null } : prev)
  }

  async function handleCancelSummary() {
    if (!videoId) return
    stopSummaryPolling(); stopSummaryTimer()
    try { await cancelSummary(videoId) }
    catch (err) { console.error('[Result] cancelSummary failed:', err) }
    setSummaryElapsedSeconds(null); summaryElapsedRef.current = null; setLocalSummaryDuration(null)
    setResult(prev => prev ? { ...prev, summary_status: null, summary_text: null, summary_duration_seconds: null } : prev)
  }

  async function handleDelete() {
    if (!videoId) return
    if (!window.confirm('Delete this video and all its data? This cannot be undone.')) return
    try { await deleteResult(videoId); navigate('/history') }
    catch (err) { console.error('[Result] deleteResult failed:', err) }
  }

  async function handleCleanupModelChange(newModel: string) {
    setCleanupModel(newModel)
    try {
      await saveSettings('cleanup', {
        system_prompt: cleanupPromptsRef.current.system_prompt,
        user_prompt_template: cleanupPromptsRef.current.user_prompt_template,
        model: newModel || null,
      })
    } catch (err) { console.error('[Result] saveSettings cleanup model failed:', err) }
  }

  async function handleSummaryModelChange(newModel: string) {
    setSummaryModel(newModel)
    try {
      await saveSettings('summarization', {
        system_prompt: summaryPromptsRef.current.system_prompt,
        user_prompt_template: summaryPromptsRef.current.user_prompt_template,
        model: newModel || null,
      })
    } catch (err) { console.error('[Result] saveSettings summary model failed:', err) }
  }

  async function handleCleanup() {
    if (!videoId || !result) return
    requestNotifyPermission()
    try {
      setCleanupError('')
      await startCleanup(videoId)
      setLocalCleanupDuration(null)
      prevCleanupStatusRef.current = 'processing'
      startCleanupTimer()
      setResult({ ...result, cleanup_status: 'processing', cleanup_duration_seconds: null })
      stopPolling()
      pollRef.current = setInterval(() => loadResult(false), 3000)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      console.error('[Cleanup] failed:', err)
      setCleanupError(msg)
    }
  }

  async function handleSummarize() {
    if (!videoId || !result) return
    requestNotifyPermission()
    try {
      setSummaryError('')
      await startSummary(videoId)
      setLocalSummaryDuration(null)
      prevSummaryStatusRef.current = 'processing'
      startSummaryTimer()
      setResult({ ...result, summary_status: 'processing', summary_duration_seconds: null })
      stopSummaryPolling()
      summaryPollRef.current = setInterval(() => loadResult(false), 3000)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      console.error('[Summary] failed:', err)
      setSummaryError(msg)
    }
  }

  if (error) return (
    <div className="container">
      <div className="card"><div className="error-box">{error}</div></div>
    </div>
  )
  if (!result) return (
    <div className="container">
      <div className="card"><div className="status-box"><div className="spinner" /></div></div>
    </div>
  )

  const cleanupDuration = result.cleanup_duration_seconds ?? localCleanupDuration
  const summaryDuration = result.summary_duration_seconds ?? localSummaryDuration

  return (
    <>
    <div className="container">
      <div className="card">
        <h2>{result.title ?? 'Untitled'}</h2>
        <div className="meta">
          {result.author && <div className="meta-item">Channel: <span>{result.author}</span></div>}
          <div className="meta-item">Duration: <span>{formatDuration(result.duration)}</span></div>
          {result.language && <div className="meta-item">Language: <span>{result.language.toUpperCase()}</span></div>}
          {(() => {
            const subtitlesCount = result.char_count ?? result.formatted_text?.length ?? null
            const cleanedCount = result.cleaned_text?.length ?? null
            const summaryCount = result.summary_text?.length ?? null
            const displayCount =
              activeTab === 'summary' ? summaryCount :
              activeTab === 'cleaned' ? cleanedCount :
              subtitlesCount
            return (subtitlesCount != null || cleanedCount != null || summaryCount != null) ? (
              <div className="meta-item">Characters: <span>
                {displayCount != null ? displayCount.toLocaleString() : '—'}
              </span></div>
            ) : null
          })()}
          {activeTab === 'cleaned' && (
            result.cleanup_status === 'processing' && cleanupElapsedSeconds != null ? (
              <div className="meta-item">
                Cleaning: <span>{formatDuration(cleanupElapsedSeconds)}</span>
                {result.cleanup_paragraphs_done != null && result.cleanup_paragraphs_total != null && (
                  <span className="meta-model"> · paragraph {result.cleanup_paragraphs_done} / {result.cleanup_paragraphs_total}</span>
                )}
              </div>
            ) : cleanupDuration != null ? (
              <div className="meta-item">
                Cleaned in: <span>{formatDuration(cleanupDuration)}</span>
                {result.cleanup_model && <span className="meta-model"> · {result.cleanup_model}</span>}
              </div>
            ) : null
          )}
          {activeTab === 'summary' && (
            result.summary_status === 'processing' && summaryElapsedSeconds != null ? (
              <div className="meta-item">
                Summarizing: <span>{formatDuration(summaryElapsedSeconds)}</span>
                {result.summary_chunks_done != null && result.summary_chunks_total != null && (
                  <span className="meta-model"> · chunk {result.summary_chunks_done} / {result.summary_chunks_total}</span>
                )}
              </div>
            ) : summaryDuration != null ? (
              <div className="meta-item">
                Summarized in: <span>{formatDuration(summaryDuration)}</span>
                {result.summary_model && <span className="meta-model"> · {result.summary_model}</span>}
                {result.summary_mode === 'map_reduce' && result.summary_chunks_count != null && (
                  <span className="meta-model"> · {result.summary_chunks_count} chunks</span>
                )}
                {(() => {
                  const inputLen = result.cleaned_text?.length ?? result.formatted_text?.length ?? null
                  const outputLen = result.summary_text?.length ?? null
                  if (!inputLen || !outputLen || outputLen >= inputLen) return null
                  const pct = Math.round((1 - outputLen / inputLen) * 100)
                  return <span className="meta-model"> · {pct}% compressed</span>
                })()}
              </div>
            ) : null
          )}
          <div className="meta-item">Saved: <span>{formatDate(result.created_at)}</span></div>
        </div>

        <div className="actions">
          <button className="btn btn-secondary" onClick={handleCopy}>
            {copied ? 'Copied!' : 'Copy text'}
          </button>

          {activeTab === 'cleaned' && (<>
            <select
              className="model-select-inline"
              value={cleanupModel}
              onChange={e => handleCleanupModelChange(e.target.value)}
              disabled={models.length === 0}
              title={models.length === 0 ? 'Ollama offline — cannot load models' : 'Model for AI cleanup'}
            >
              <option value="">— cleanup model —</option>
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            {result.cleanup_status === 'processing' ? (
              <button className="btn btn-secondary" onClick={handleCancelCleanup}>✕ Stop</button>
            ) : (
              <button className="btn btn-ai" onClick={handleCleanup}>
                {result.cleanup_status === 'done' ? '↺ Re-run AI cleanup' : '✦ Clean with AI'}
              </button>
            )}
          </>)}

          {activeTab === 'summary' && (<>
            <select
              className="model-select-inline"
              value={summaryModel}
              onChange={e => handleSummaryModelChange(e.target.value)}
              disabled={models.length === 0}
              title={models.length === 0 ? 'Ollama offline — cannot load models' : 'Model for summarization'}
            >
              <option value="">— summary model —</option>
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            {result.summary_status === 'processing' ? (
              <button className="btn btn-secondary" onClick={handleCancelSummary}>✕ Stop</button>
            ) : (
              <button className="btn btn-ai" onClick={handleSummarize}>
                {result.summary_status === 'done' ? '↺ Re-run summary' : '✦ Summarize'}
              </button>
            )}
          </>)}

          <a className="btn btn-secondary" href={result.url} target="_blank" rel="noreferrer">
            Open video
          </a>
          <button className="btn btn-danger" onClick={handleDelete}>Delete</button>
        </div>

        {activeTab === 'cleaned' && (result.cleanup_status === 'failed' || cleanupError) && (
          <div className="cleanup-error">
            {cleanupError || 'Cleanup failed — make sure Ollama is running and a model is selected.'}
          </div>
        )}
        {activeTab === 'summary' && (result.summary_status === 'failed' || summaryError) && (
          <div className="cleanup-error">
            {summaryError || 'Summarization failed — make sure Ollama is running and a model is selected.'}
          </div>
        )}

        <div className="result-tabs">
          <button
            className={`result-tab ${activeTab === 'subtitles' ? 'active' : ''}`}
            onClick={() => setActiveTab('subtitles')}
          >
            Subtitles
          </button>
          <button
            className={`result-tab ${activeTab === 'cleaned' ? 'active' : ''}`}
            onClick={() => setActiveTab('cleaned')}
          >
            {result.cleanup_status === 'processing'
              ? <><span className="tab-spinner" />Cleaning…</>
              : 'Cleaned'}
          </button>
          <button
            className={`result-tab ${activeTab === 'summary' ? 'active' : ''}`}
            onClick={() => setActiveTab('summary')}
          >
            {result.summary_status === 'processing'
              ? <><span className="tab-spinner" />Summarizing…</>
              : 'Summary'}
          </button>
        </div>

        {activeTab === 'summary' ? (
          <>
            {!result.summary_text ? (
              <div className="empty">
                {result.summary_status === 'processing'
                  ? 'Summarization is running…'
                  : result.summary_status === 'failed'
                    ? 'Summary failed. Click "↺ Re-run summary" to try again.'
                    : 'No summary yet. Click "✦ Summarize" above to generate one.'}
              </div>
            ) : (
              <>
                <div className="formatted-text">{result.summary_text}</div>

                {/* Chat thread */}
                {chatHistory.length > 0 && (
                  <div className="chat-thread">
                    {chatHistory.map((msg, i) => (
                      <div key={i} className={`chat-msg chat-msg--${msg.role}`}>
                        {msg.content || (msg.role === 'assistant' && isChatting
                          ? <span className="chat-typing">…</span>
                          : null)}
                      </div>
                    ))}
                    <div ref={chatEndRef} />
                  </div>
                )}
                {/* Spacer so content isn't hidden behind fixed input bar */}
                <div style={{ height: '80px' }} />
              </>
            )}
          </>
        ) : activeTab === 'cleaned' && !result.cleaned_text ? (
          <div className="empty">
            {result.cleanup_status === 'processing'
              ? 'AI cleanup is running…'
              : result.cleanup_status === 'failed'
                ? 'Cleanup failed. Click "↺ Re-run AI cleanup" to try again.'
                : 'No cleaned version yet. Click "✦ Clean with AI" above to start.'}
          </div>
        ) : (
          <div className="formatted-text">{displayText ? renderText(displayText) : null}</div>
        )}
      </div>
    </div>

    {/* Fixed chat input bar — only on Summary tab when done */}
    {activeTab === 'summary' && result.summary_status === 'done' && result.summary_text && ollamaUrl && summaryModel && (
      <div className="chat-input-bar">
        {(() => {
          const sourceLen = (result.cleaned_text ?? result.formatted_text ?? '').length
          return sourceLen > CHAT_WARN_CHARS ? (
            <div className="chat-warn">
              ⚠ Text is very long ({Math.round(sourceLen / 1000)}K chars) — response quality may vary
            </div>
          ) : null
        })()}
        {chatHistory.length === 0 && (
          <div className="chat-hint">Ask a follow-up question about the video</div>
        )}
        {chatHistory.length > 0 && (
          <button className="chat-copy-btn" onClick={copyChat}>
            {chatCopied ? 'Copied!' : 'Copy dialogue'}
          </button>
        )}
        <div className="chat-input-wrap">
          <textarea
            ref={chatInputRef}
            className="chat-input"
            rows={1}
            placeholder="Ask about the video…"
            value={chatInput}
            disabled={isChatting}
            onChange={e => {
              setChatInput(e.target.value)
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
            }}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage() }
            }}
          />
          <button
            className="chat-send-btn"
            onClick={sendChatMessage}
            disabled={isChatting || !chatInput.trim()}
            title="Send"
          >
            {isChatting ? '…' : '➤'}
          </button>
        </div>
      </div>
    )}
    </>
  )
}
