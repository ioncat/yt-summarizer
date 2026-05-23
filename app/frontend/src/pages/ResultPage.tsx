import { useEffect, useRef, useState, lazy, Suspense } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  getResult, deleteResult,
  startCleanup, cancelCleanup,
  startSummary, cancelSummary,
  startMindmap,
  reextractSubtitles,
  saveChatHistory, clearChatHistory,
  getSettings, getModels, saveSettings,
  ResultResponse,
} from '../api'
import { renderText } from '../utils/renderText'

const MindmapView = lazy(() => import('../components/MindmapView'))

type Tab = 'subtitles' | 'cleaned' | 'summary' | 'chat'

function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="formatted-text markdown-content">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  )
}

function formatDuration(seconds: number | null): string {
  if (seconds === 0) return '0:00'
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const yyyy = d.getFullYear()
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${dd}.${mm}.${yyyy}, ${hh}:${min}`
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
  const [markdownEnabled, setMarkdownEnabled] = useState(() =>
    localStorage.getItem('yt-md-enabled') === 'true'
  )
  const [mindmapEnabled, setMindmapEnabled] = useState(false)
  const [mindmapError, setMindmapError] = useState('')
  const mindmapPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const prevMindmapStatusRef = useRef<string | null | undefined>(undefined)
  const [reextractLang, setReextractLang] = useState('auto')
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
  const chatHistoryLoadedRef = useRef(false)
  const autoSummarizeAfterCleanupRef = useRef(false)
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
  function stopMindmapPolling() {
    if (mindmapPollRef.current) { clearInterval(mindmapPollRef.current); mindmapPollRef.current = null }
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
        const prevMindmap = prevMindmapStatusRef.current
        prevCleanupStatusRef.current = data.cleanup_status
        prevSummaryStatusRef.current = data.summary_status
        prevMindmapStatusRef.current = data.mindmap_status
        setResult(data)

        // Load chat history once on first successful fetch
        if (!chatHistoryLoadedRef.current) {
          chatHistoryLoadedRef.current = true
          if (data.chat_history && data.chat_history.length > 0) {
            setChatHistory(data.chat_history as Array<{ role: 'user' | 'assistant'; content: string }>)
          }
        }

        // Tab auto-switching on initial load
        if (switchTab) {
          if (data.summary_status === 'done') setActiveTab('summary')
          else if (data.cleanup_status === 'done') setActiveTab('cleaned')
          else setActiveTab('subtitles')
        } else {
          if (prevCleanup === 'processing' && data.cleanup_status === 'done') {
            notify('AI Cleanup complete', data.title ?? undefined)
            if (autoSummarizeAfterCleanupRef.current) {
              autoSummarizeAfterCleanupRef.current = false
              // Trigger summary immediately after cleanup
              startSummary(videoId!).then(() => {
                prevSummaryStatusRef.current = 'processing'
                startSummaryTimer()
                setResult(d => d ? { ...d, summary_status: 'processing', summary_duration_seconds: null } : d)
                stopSummaryPolling()
                summaryPollRef.current = setInterval(() => loadResult(false), 3000)
              }).catch(() => {})
            } else {
              setActiveTab('cleaned')
            }
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

        // Mindmap polling management
        if (data.mindmap_status !== 'processing') {
          if (prevMindmap === 'processing' && data.mindmap_status === 'done') {
            // mindmap ready — MindmapView will re-render via result state
          }
          stopMindmapPolling()
        } else if (!mindmapPollRef.current) {
          mindmapPollRef.current = setInterval(() => loadResult(false), 3000)
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
      stopMindmapPolling()
      stopCleanupTimer()
      stopSummaryTimer()
    }
  }, [videoId])

  // While re-extract is in progress, poll every 3s until backend clears the flag
  useEffect(() => {
    if (!result?.reextract_in_progress) return
    const id = setInterval(() => loadResult(), 3000)
    return () => clearInterval(id)
  }, [result?.reextract_in_progress])

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

  // Chat history is never auto-reset — user manages it manually via Clear chat

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
      // Persist after successful exchange
      if (fullResponse && videoId) {
        const savedHistory = [
          ...chatHistory,
          { role: 'user' as const, content: question },
          { role: 'assistant' as const, content: fullResponse },
        ]
        saveChatHistory(videoId, savedHistory).catch(() => {})
        setActiveTab('chat')
      }
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

  async function deleteChatMessage(index: number) {
    const updated = chatHistory.filter((_, i) => i !== index)
    setChatHistory(updated)
    if (videoId) saveChatHistory(videoId, updated).catch(() => {})
  }

  async function handleClearChat() {
    if (!window.confirm('Clear entire chat history? This cannot be undone.')) return
    setChatHistory([])
    ollamaMessagesRef.current = []
    if (videoId) clearChatHistory(videoId).catch(() => {})
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
    activeTab === 'chat' ? null :
    result?.formatted_text

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

  async function handleReextract() {
    if (!videoId) return
    const ok = window.confirm(
      'Re-extract subtitles from YouTube?\n\n' +
      'This will:\n' +
      '• Replace the current Subtitles tab content with a fresh download\n' +
      '• Clear the Cleaned tab (you will need to re-run AI Cleanup)\n' +
      '• Clear the Summary tab (you will need to re-run summarization)\n\n' +
      'Continue?'
    )
    if (!ok) return
    try {
      await reextractSubtitles(videoId, reextractLang)
      // Optimistic UI flag — polling will refresh once the backend writes new text
      setResult(prev => prev ? { ...prev, reextract_in_progress: true } : prev)
      // Force a quick first poll
      loadResult()
    } catch (err: any) {
      console.error('[Result] reextract failed:', err)
      setError(err.message ?? 'Failed to re-extract subtitles')
    }
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

    // If cleanup was never run, offer to run the full pipeline first
    if (!result.cleanup_status && !result.cleaned_text) {
      const confirmed = window.confirm(
        'AI Cleanup has not been run yet.\n\nTo get a quality summary, cleanup should run first.\n\nRun cleanup → summarize pipeline now?'
      )
      if (!confirmed) return
      autoSummarizeAfterCleanupRef.current = true
      await handleCleanup()
      return
    }

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
          {/* ── Row 1: video info ── */}
          <div className="meta-row">
            {result.author && <>
              <span className="meta-chip" title="YouTube channel">
                <span className="meta-label">Channel:</span> {result.author}
              </span>
              <span className="meta-sep">•</span>
            </>}
            <span className="meta-chip" title="Video duration">
              <span className="meta-label">Duration</span> {formatDuration(result.duration)}
            </span>
            {result.language && <>
              <span className="meta-sep">•</span>
              <span className="meta-chip" title="Detected language">
                <span className="meta-label">Language</span> {result.language.toUpperCase()}
              </span>
            </>}
            {(() => {
              const subtitlesCount = result.char_count ?? result.formatted_text?.length ?? null
              const cleanedCount = result.cleaned_text?.length ?? null
              const summaryCount = result.summary_text?.length ?? null
              const displayCount =
                activeTab === 'summary' ? summaryCount :
                activeTab === 'cleaned' ? cleanedCount :
                subtitlesCount
              return displayCount != null ? <>
                <span className="meta-sep">•</span>
                <span className="meta-chip" title="Character count for current tab">
                  <span className="meta-label">Characters</span> {displayCount.toLocaleString()}
                </span>
              </> : null
            })()}
            <span className="meta-sep">•</span>
            <span className="meta-chip" title="Date added to history">
              <span className="meta-label">Saved:</span> {formatDate(result.created_at)}
            </span>
          </div>

          {/* ── Divider + Row 2: stage info (tab-dependent) ── */}
          {activeTab === 'cleaned' && (
            result.cleanup_status === 'processing' && cleanupElapsedSeconds != null ? (
              <div className="meta-row meta-row--stage">
                <span className="meta-chip" title="AI cleanup in progress">
                  <span className="meta-label">Cleaning</span> {formatDuration(cleanupElapsedSeconds)}
                </span>
                {result.cleanup_paragraphs_done != null && result.cleanup_paragraphs_total != null && <>
                  <span className="meta-sep">•</span>
                  <span className="meta-chip" title="Paragraphs processed so far">
                    paragraph {result.cleanup_paragraphs_done} / {result.cleanup_paragraphs_total}
                  </span>
                </>}
              </div>
            ) : cleanupDuration != null ? (
              <div className="meta-row meta-row--stage">
                <span className="meta-chip" title="Time spent on AI cleanup">
                  <span className="meta-label">Cleaned in:</span> {formatDuration(cleanupDuration)}
                </span>
                {result.cleanup_model && <>
                  <span className="meta-sep">•</span>
                  <span className="meta-chip" title="Model used for cleanup">{result.cleanup_model}</span>
                </>}
                <span className="meta-sep">•</span>
                <span className="meta-chip meta-method" title="Processing method">AI Cleanup</span>
                {(() => {
                  const count = result.cleaned_text
                    ? result.cleaned_text.split('\n\n').filter(p => p.trim()).length
                    : null
                  return count != null ? <>
                    <span className="meta-sep">•</span>
                    <span className="meta-chip" title="Number of paragraphs processed">{count} paragraphs</span>
                  </> : null
                })()}
                {result.cleanup_finished_at && <>
                  <span className="meta-sep">•</span>
                  <span className="meta-chip" title="When AI cleanup finished">{formatDate(result.cleanup_finished_at)}</span>
                </>}
              </div>
            ) : null
          )}
          {activeTab === 'summary' && (
            result.summary_status === 'processing' && summaryElapsedSeconds != null ? (
              <div className="meta-row meta-row--stage">
                <span className="meta-chip" title="Summarization in progress">
                  <span className="meta-label">Summarizing</span> {formatDuration(summaryElapsedSeconds)}
                </span>
                {result.summary_chunks_done != null && result.summary_chunks_total != null && <>
                  <span className="meta-sep">•</span>
                  <span className="meta-chip" title="Chunks/chapters processed so far">
                    {result.chapters ? 'chapter' : 'chunk'} {result.summary_chunks_done} / {result.summary_chunks_total}
                  </span>
                </>}
              </div>
            ) : summaryDuration != null ? (
              <div className="meta-row meta-row--stage">
                <span className="meta-chip" title="Time spent on summarization">
                  <span className="meta-label">Summarized in</span> {formatDuration(summaryDuration)}
                </span>
                {result.summary_model && <>
                  <span className="meta-sep">•</span>
                  <span className="meta-chip" title="Model used for summarization">{result.summary_model}</span>
                </>}
                {result.summary_mode === 'single' && <>
                  <span className="meta-sep">•</span>
                  <span className="meta-chip meta-method" title="Processing method">Single Pass</span>
                </>}
                {result.summary_mode === 'map_reduce' && <>
                  <span className="meta-sep">•</span>
                  <span className="meta-chip meta-method" title="Processing method: text split into chunks, each summarized, then combined">Map-Reduce</span>
                  {result.summary_chunks_count != null && <>
                    <span className="meta-sep">•</span>
                    <span className="meta-chip" title="Number of chunks processed">{result.summary_chunks_count} chunks</span>
                  </>}
                </>}
                {result.summary_mode === 'full_extract' && <>
                  <span className="meta-sep">•</span>
                  <span className="meta-chip meta-method" title="Processing method: each chapter extracted independently, no compression">Full Extract</span>
                  {result.summary_chunks_count != null && <>
                    <span className="meta-sep">•</span>
                    <span className="meta-chip" title="Number of chapters processed">{result.summary_chunks_count} chapters</span>
                  </>}
                </>}
                {(() => {
                  const inputLen = result.cleaned_text?.length ?? result.formatted_text?.length ?? null
                  const outputLen = result.summary_text?.length ?? null
                  if (!inputLen || !outputLen || outputLen >= inputLen) return null
                  const pct = Math.round((1 - outputLen / inputLen) * 100)
                  return <>
                    <span className="meta-sep">•</span>
                    <span className="meta-chip" title="How much the text was compressed vs input">{pct}% compressed</span>
                  </>
                })()}
                {result.summary_finished_at && <>
                  <span className="meta-sep">•</span>
                  <span className="meta-chip" title="When summarization finished">{formatDate(result.summary_finished_at)}</span>
                </>}
              </div>
            ) : null
          )}
        </div>

        <hr className="section-divider" />

        <div className="actions">
          {/* ── Row 1 ── */}
          <div className="actions-row">
            {activeTab === 'subtitles' && <>
              <select
                className="model-select-inline"
                value={reextractLang}
                onChange={e => setReextractLang(e.target.value)}
                disabled={!!result.reextract_in_progress}
                title="Language for subtitle re-extraction"
              >
                <option value="auto">Auto</option>
                <option value="ru">Russian</option>
                <option value="en">English</option>
                <option value="uk">Ukrainian</option>
              </select>
              <button
                className="btn btn-secondary"
                onClick={handleReextract}
                disabled={
                  !!result.reextract_in_progress ||
                  result.cleanup_status === 'processing' ||
                  result.summary_status === 'processing'
                }
                title="Re-fetch subtitles from YouTube. Cleanup and Summary will be cleared."
              >
                {result.reextract_in_progress ? '↻ Re-extracting…' : '↻ Re-extract'}
              </button>
              <a className="btn btn-secondary" href={`/benchmark/${result.video_id}`}>⚖ Benchmark</a>
            </>}

            {activeTab === 'cleaned' && <>
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
              <a className="btn btn-secondary" href={`/benchmark/${result.video_id}`}>⚖ Benchmark</a>
            </>}

            {activeTab === 'summary' && <>
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
              <a className="btn btn-secondary" href={`/benchmark/${result.video_id}`}>⚖ Benchmark</a>
            </>}
          </div>

          {/* ── Row 2 ── */}
          <div className="actions-row">
            {activeTab === 'subtitles' && <>
              <button className="btn btn-secondary" onClick={handleCopy}>
                {copied ? 'Copied!' : 'Copy text'}
              </button>
              <a className="btn btn-secondary" href={result.url} target="_blank" rel="noreferrer">Open video</a>
            </>}

            {(activeTab === 'cleaned' || activeTab === 'summary') && <>
              <button className="btn btn-secondary" onClick={handleCopy}>
                {copied ? 'Copied!' : 'Copy text'}
              </button>
              <a className="btn btn-secondary" href={result.url} target="_blank" rel="noreferrer">Open video</a>
            </>}

            <button className="btn btn-danger" onClick={handleDelete}>Delete</button>
          </div>
        </div>

        <hr className="section-divider" />

        {activeTab === 'cleaned' && (result.cleanup_status === 'failed' || cleanupError) && (
          <div className="cleanup-error">
            {cleanupError || 'Cleanup failed. Possible causes: Ollama is not running, no model is selected, or the model returned no output (e.g. due to timeout on large paragraphs). Check backend log for details.'}
          </div>
        )}
        {activeTab === 'summary' && (result.summary_status === 'failed' || summaryError) && (
          <div className="cleanup-error">
            {summaryError || 'Summarization failed. Possible causes: Ollama is not running, no model is selected, or a stage (MAP / REDUCE / chapter) timed out. For long videos (>50K chars without chapters) the REDUCE step may exceed the model context — try a stronger model, or wait for hierarchical map-reduce (Epic 18). Check backend log for details.'}
          </div>
        )}

        <div className="result-tabs-bar">
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
          {chatHistory.length > 0 && (
            <button
              className={`result-tab ${activeTab === 'chat' ? 'active' : ''}`}
              onClick={() => setActiveTab('chat')}
            >
              Chat <span className="tab-count">({chatHistory.length})</span>
            </button>
          )}
        </div>
          {activeTab === 'summary' && result.summary_text && (
            <button
              className={`md-toggle ${mindmapEnabled ? 'md-toggle--on' : ''}`}
              onClick={async () => {
                if (!mindmapEnabled) {
                  setMindmapEnabled(true)
                  // If no mindmap yet — trigger generation
                  if (!result.mindmap_text && result.mindmap_status !== 'processing') {
                    setMindmapError('')
                    try {
                      await startMindmap(videoId!)
                      setResult(r => r ? { ...r, mindmap_status: 'processing' } : r)
                      prevMindmapStatusRef.current = 'processing'
                      stopMindmapPolling()
                      mindmapPollRef.current = setInterval(() => loadResult(false), 3000)
                    } catch (e: unknown) {
                      setMindmapError(e instanceof Error ? e.message : 'Failed')
                    }
                  }
                } else {
                  setMindmapEnabled(false)
                }
              }}
              title={mindmapEnabled ? 'Mindmap ON — click to switch to text' : 'Text view — click to generate mindmap'}
            >🗺</button>
          )}
          <button
            className={`md-toggle ${markdownEnabled ? 'md-toggle--on' : ''}`}
            onClick={() => {
              const next = !markdownEnabled
              setMarkdownEnabled(next)
              localStorage.setItem('yt-md-enabled', String(next))
            }}
            title={markdownEnabled ? 'Markdown rendering ON — click to switch to plain text' : 'Plain text — click to enable Markdown rendering'}
          >MD</button>
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
            ) : mindmapEnabled ? (
              result.mindmap_status === 'processing' ? (
                <div className="empty"><span className="tab-spinner" /> Generating mindmap…</div>
              ) : result.mindmap_status === 'failed' || mindmapError ? (
                <div className="cleanup-error">
                  {mindmapError || 'Mindmap generation failed. Check that Ollama is running and a model is selected in Settings → Summarization.'}
                </div>
              ) : result.mindmap_text ? (
                <Suspense fallback={<div className="empty">Loading…</div>}>
                  <MindmapView
                    text={result.mindmap_text}
                    title={result.title ?? undefined}
                    onRegenerate={async () => {
                      setMindmapError('')
                      try {
                        await startMindmap(videoId!, true)
                        setResult(r => r ? { ...r, mindmap_status: 'processing', mindmap_text: null } : r)
                        prevMindmapStatusRef.current = 'processing'
                        stopMindmapPolling()
                        mindmapPollRef.current = setInterval(() => loadResult(false), 3000)
                      } catch (e: unknown) {
                        setMindmapError(e instanceof Error ? e.message : 'Failed')
                      }
                    }}
                  />
                </Suspense>
              ) : (
                <div className="empty">Generating mindmap…</div>
              )
            ) : (
              <>
                {markdownEnabled
                  ? <MarkdownContent text={result.summary_text!} />
                  : <div className="formatted-text">{renderText(result.summary_text!)}</div>
                }

                {/* Spacer so content isn't hidden behind fixed input bar */}
                <div style={{ height: '80px' }} />
              </>
            )}
          </>
        ) : activeTab === 'chat' ? (
          <>
            <div className="chat-thread-header">
              <button
                className="btn-copy-chat"
                onClick={() => {
                  const text = chatHistory
                    .filter(m => m.content)
                    .map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`)
                    .join('\n\n')
                  navigator.clipboard.writeText(text)
                }}
                title="Copy entire chat"
              >⎘ Copy chat</button>
              <button
                className="btn-copy-chat"
                onClick={handleClearChat}
                title="Delete entire chat history"
                style={{ marginLeft: '0.5rem', color: 'var(--err)' }}
              >🗑 Clear chat</button>
            </div>
            <div className="chat-thread">
              {chatHistory.map((msg, i) => (
                <div key={i} className={`chat-msg chat-msg--${msg.role}`}>
                  {msg.content
                    ? (markdownEnabled && msg.role === 'assistant'
                        ? <ReactMarkdown>{msg.content}</ReactMarkdown>
                        : msg.content)
                    : (msg.role === 'assistant' && isChatting
                        ? (
                          <span className="chat-typing">
                            <span className="chat-typing-dot" />
                            <span className="chat-typing-dot" />
                            <span className="chat-typing-dot" />
                          </span>
                        )
                        : null)}
                  {msg.content && (<>
                    <button
                      className="chat-msg-copy"
                      onClick={() => navigator.clipboard.writeText(msg.content)}
                      title="Copy message"
                    >⎘</button>
                    <button
                      className="chat-msg-copy chat-msg-delete"
                      onClick={() => deleteChatMessage(i)}
                      title="Delete message"
                    >🗑</button>
                  </>)}
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>
            <div style={{ height: '80px' }} />
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
          displayText
            ? markdownEnabled
              ? <MarkdownContent text={displayText} />
              : <div className="formatted-text">{renderText(displayText)}</div>
            : null
        )}
      </div>
    </div>

    {/* Fixed chat input bar — on Summary tab (start chat) and Chat tab (continue) */}
    {(activeTab === 'summary' || activeTab === 'chat') && result.summary_status === 'done' && result.summary_text && ollamaUrl && summaryModel && (
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
            {isChatting ? <span className="chat-send-spinner" /> : '➤'}
          </button>
        </div>
      </div>
    )}
    </>
  )
}
