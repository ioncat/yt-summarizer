import { useEffect, useRef, useState, lazy, Suspense } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  getResult, deleteResult,
  cancelCleanup,
  cancelSummary,
  cancelMindmap,
  reextractSubtitles,
  saveChatHistory, clearChatHistory,
  getSettings, getModels, saveSettings,
  queueBulkAdd, toggleFavorite,
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
  const ollamaMessagesRef = useRef<Array<{ role: string; content: string }>>([])
  const chatEndRef = useRef<HTMLDivElement>(null)
  const chatInputRef = useRef<HTMLTextAreaElement>(null)
  const chatHistoryLoadedRef = useRef(false)
  const autoSummarizeAfterCleanupRef = useRef(false)
  const [queuedMsg, setQueuedMsg] = useState<string | null>(null)
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
      await queueBulkAdd([result.url], ['cleanup'])
      setQueuedMsg('cleanup')
      // Start polling — worker will update cleanup_status in DB
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
      // Queue both stages together
      try {
        setSummaryError('')
        await queueBulkAdd([result.url], ['cleanup', 'summary'])
        setQueuedMsg('cleanup+summary')
        stopPolling()
        pollRef.current = setInterval(() => loadResult(false), 3000)
      } catch (err: unknown) {
        console.error('[Pipeline] failed:', err)
        setSummaryError(err instanceof Error ? err.message : 'Unknown error')
      }
      return
    }

    requestNotifyPermission()
    try {
      setSummaryError('')
      await queueBulkAdd([result.url], ['summary'])
      setQueuedMsg('summary')
      stopSummaryPolling()
      summaryPollRef.current = setInterval(() => loadResult(false), 3000)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      console.error('[Summary] failed:', err)
      setSummaryError(msg)
    }
  }

  async function handleMindmap(force = false) {
    if (!videoId || !result) return
    try {
      setMindmapError('')
      if (force) {
        // Reset mindmap_text optimistically so UI shows generating state
        setResult(r => r ? { ...r, mindmap_text: null, mindmap_status: null } : r)
      }
      await queueBulkAdd([result.url], ['mindmap'])
      setQueuedMsg('mindmap')
      stopMindmapPolling()
      mindmapPollRef.current = setInterval(() => loadResult(false), 3000)
    } catch (err: unknown) {
      console.error('[Mindmap] failed:', err)
      setMindmapError(err instanceof Error ? err.message : 'Unknown error')
    }
  }

  if (error) return (
    <div className="p-6 md:p-gutter max-w-[1200px] mx-auto w-full">
      <div className="bg-error-container text-on-error-container rounded-xl px-6 py-4 text-body-md">{error}</div>
    </div>
  )
  if (!result) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <span className="material-symbols-outlined text-secondary animate-spin" style={{ fontSize: '36px', animation: 'spin 1.2s linear infinite' }}>progress_activity</span>
    </div>
  )

  const cleanupDuration = result.cleanup_duration_seconds ?? localCleanupDuration
  const summaryDuration = result.summary_duration_seconds ?? localSummaryDuration

  // Compression %
  const compressionPct = (() => {
    const inputLen = result.cleaned_text?.length ?? result.formatted_text?.length ?? null
    const outputLen = result.summary_text?.length ?? null
    if (!inputLen || !outputLen || outputLen >= inputLen) return null
    return Math.round((1 - outputLen / inputLen) * 100)
  })()

  // Active tab char count
  const displayCharCount = (() => {
    const subtitlesCount = result.char_count ?? result.formatted_text?.length ?? null
    const cleanedCount = result.cleaned_text?.length ?? null
    const summaryCount = result.summary_text?.length ?? null
    return activeTab === 'summary' ? summaryCount : activeTab === 'cleaned' ? cleanedCount : subtitlesCount
  })()

  // Stage ribbon content
  const showCleanupRibbon = activeTab === 'cleaned' && (
    (result.cleanup_status === 'processing' && cleanupElapsedSeconds != null) || cleanupDuration != null
  )
  const showSummaryRibbon = activeTab === 'summary' && (
    (result.summary_status === 'processing' && summaryElapsedSeconds != null) || summaryDuration != null
  )

  function tabClass(tab: Tab) {
    return activeTab === tab
      ? 'px-1 py-3 text-primary font-bold text-label-md border-b-2 border-primary transition-colors'
      : 'px-1 py-3 text-on-surface-variant text-label-md hover:text-on-surface transition-colors border-b-2 border-transparent'
  }

  function actionBtn(primary: boolean, danger = false) {
    if (danger) return 'flex items-center gap-2 px-4 py-2 bg-surface-container-lowest text-error border border-error/30 rounded-lg text-label-md hover:bg-error/5 active:scale-95 transition-all'
    if (primary) return 'flex items-center gap-2 px-5 py-2 bg-primary-container text-on-primary-container rounded-lg text-label-md font-semibold active:scale-95 transition-all shadow-sm hover:opacity-90'
    return 'flex items-center gap-2 px-4 py-2 bg-surface-container-high text-on-surface-variant border border-outline-variant rounded-lg text-label-md hover:bg-surface-container-highest active:scale-95 transition-all'
  }

  const metaSep = <span className="w-1 h-1 rounded-full bg-outline-variant flex-shrink-0" />

  return (
    <div className="p-6 md:p-gutter max-w-[1200px] mx-auto w-full pb-32 space-y-6">

      {/* ── Main card ── */}
      <section className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm overflow-hidden">

        {/* Card header: title + star */}
        <div className="p-6 border-b border-outline-variant">
          <div className="flex justify-between items-start mb-4 gap-4">
            <h2 className="text-headline-xl text-on-surface leading-tight">{result.title ?? 'Untitled'}</h2>
            <button
              className={`material-symbols-outlined flex-shrink-0 transition-colors mt-1 ${result.is_favorite ? 'text-amber-400' : 'text-on-surface-variant hover:text-amber-400'}`}
              style={{ fontSize: '28px', fontVariationSettings: result.is_favorite ? "'FILL' 1" : "'FILL' 0", background: 'none', border: 'none', cursor: 'pointer' }}
              onClick={async () => {
                const r = await toggleFavorite(videoId!)
                setResult(prev => prev ? { ...prev, is_favorite: r.is_favorite } : prev)
              }}
              title={result.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
            >star</button>
          </div>

          {/* Meta row 1: video info */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-secondary text-body-sm">
            {result.author && (
              <div className="flex items-center gap-1">
                <span className="font-semibold text-on-surface">Channel:</span> {result.author}
              </div>
            )}
            {result.author && metaSep}
            <div className="flex items-center gap-1">
              <span className="font-semibold text-on-surface">Duration:</span> {formatDuration(result.duration)}
            </div>
            {result.language && <>{metaSep}<div><span className="font-semibold text-on-surface">Language:</span> {result.language.toUpperCase()}</div></>}
            {displayCharCount != null && <>{metaSep}<div><span className="font-semibold text-on-surface">Characters:</span> {displayCharCount.toLocaleString()}</div></>}
            {metaSep}
            <div><span className="font-semibold text-on-surface">Saved:</span> {formatDate(result.created_at)}</div>
          </div>
        </div>

        {/* Queued notification banner */}
        {queuedMsg && (
          <div className="px-6 py-3 bg-secondary-container/30 border-b border-outline-variant flex items-center gap-3 text-body-sm text-on-surface">
            <span className="material-symbols-outlined text-secondary" style={{ fontSize: '16px' }}>schedule</span>
            Added to queue
            {queuedMsg === 'cleanup+summary' ? ' (cleanup → summary)' : queuedMsg === 'cleanup' ? ' (cleanup)' : queuedMsg === 'summary' ? ' (summary)' : ' (mindmap)'}
            <a href="/queue" className="text-primary hover:underline underline-offset-2 ml-1">View queue →</a>
            <button onClick={() => setQueuedMsg(null)} className="ml-auto text-on-surface-variant hover:text-on-surface transition-colors">
              <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>close</span>
            </button>
          </div>
        )}

        {/* Stage metadata ribbon — shown for Cleaned + Summary tabs when data available */}
        {(showCleanupRibbon || showSummaryRibbon) && (
          <div className="px-6 py-3 bg-surface-container-low border-b border-outline-variant flex flex-wrap gap-3 text-label-sm text-secondary items-center">
            {showCleanupRibbon && (
              result.cleanup_status === 'processing' && cleanupElapsedSeconds != null ? (
                <>
                  <span className="material-symbols-outlined text-secondary" style={{ fontSize: '16px', animation: 'spin 1.5s linear infinite' }}>progress_activity</span>
                  <span>Cleaning… {formatDuration(cleanupElapsedSeconds)}</span>
                  {result.cleanup_paragraphs_done != null && result.cleanup_paragraphs_total != null && (
                    <>{metaSep}<span>paragraph {result.cleanup_paragraphs_done} / {result.cleanup_paragraphs_total}</span></>
                  )}
                </>
              ) : cleanupDuration != null ? (
                <>
                  <div className="flex items-center gap-2"><span className="material-symbols-outlined" style={{ fontSize: '16px' }}>timer</span>Cleaned in {formatDuration(cleanupDuration)}</div>
                  {result.cleanup_model && <>{metaSep}<span className="font-bold text-on-surface">{result.cleanup_model}</span></>}
                  {metaSep}
                  <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary font-bold text-[10px] border border-primary/20">AI Cleanup</span>
                  {(() => {
                    const count = result.cleaned_text ? result.cleaned_text.split('\n\n').filter(p => p.trim()).length : null
                    return count != null ? <>{metaSep}<span>{count} paragraphs</span></> : null
                  })()}
                  {result.cleanup_finished_at && <>{metaSep}<span>{formatDate(result.cleanup_finished_at)}</span></>}
                </>
              ) : null
            )}
            {showSummaryRibbon && (
              result.summary_status === 'processing' && summaryElapsedSeconds != null ? (
                <>
                  <span className="material-symbols-outlined text-secondary" style={{ fontSize: '16px', animation: 'spin 1.5s linear infinite' }}>progress_activity</span>
                  <span>Summarizing… {formatDuration(summaryElapsedSeconds)}</span>
                  {result.summary_chunks_done != null && result.summary_chunks_total != null && (
                    <>{metaSep}<span>{result.chapters ? 'chapter' : 'chunk'} {result.summary_chunks_done} / {result.summary_chunks_total}</span></>
                  )}
                </>
              ) : summaryDuration != null ? (
                <>
                  <div className="flex items-center gap-2"><span className="material-symbols-outlined" style={{ fontSize: '16px' }}>timer</span>Summarized in {formatDuration(summaryDuration)}</div>
                  {result.summary_model && <>{metaSep}<span className="font-bold text-on-surface">{result.summary_model}</span></>}
                  {result.summary_mode === 'single' && <>{metaSep}<span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary font-bold text-[10px] border border-primary/20">Single Pass</span></>}
                  {result.summary_mode === 'map_reduce' && (
                    <>{metaSep}<span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary font-bold text-[10px] border border-primary/20">Map-Reduce</span>
                    {result.summary_chunks_count != null && <>{metaSep}<span>{result.summary_chunks_count} chunks</span></>}</>
                  )}
                  {result.summary_mode === 'full_extract' && (
                    <>{metaSep}<span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary font-bold text-[10px] border border-primary/20">Full Extract</span>
                    {result.summary_chunks_count != null && <>{metaSep}<span>{result.summary_chunks_count} chapters</span></>}</>
                  )}
                  {compressionPct != null && <>{metaSep}<span>{compressionPct}% compressed</span></>}
                  {result.summary_finished_at && <>{metaSep}<span>{formatDate(result.summary_finished_at)}</span></>}
                </>
              ) : null
            )}
          </div>
        )}

        {/* Controls row */}
        <div className="px-6 py-4 border-b border-outline-variant flex flex-wrap items-center gap-3">
          {/* Tab-dependent left actions */}
          {activeTab === 'subtitles' && (
            <>
              <select
                className="bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-label-md focus:ring-2 focus:ring-primary/20 outline-none appearance-none cursor-pointer"
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
                className={actionBtn(false)}
                onClick={handleReextract}
                disabled={!!result.reextract_in_progress || result.cleanup_status === 'processing' || result.summary_status === 'processing'}
                title="Re-fetch subtitles from YouTube. Cleanup and Summary will be cleared."
              >
                <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>refresh</span>
                {result.reextract_in_progress ? 'Re-extracting…' : 'Re-extract'}
              </button>
            </>
          )}

          {activeTab === 'cleaned' && (
            <>
              <div className="relative">
                <select
                  className="bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 pr-8 text-label-md focus:ring-2 focus:ring-primary/20 outline-none appearance-none cursor-pointer min-w-[180px]"
                  value={cleanupModel}
                  onChange={e => handleCleanupModelChange(e.target.value)}
                  disabled={models.length === 0}
                  title={models.length === 0 ? 'Ollama offline — cannot load models' : 'Model for AI cleanup'}
                >
                  <option value="">— cleanup model —</option>
                  {models.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
                <span className="material-symbols-outlined absolute right-2 top-2.5 text-secondary pointer-events-none" style={{ fontSize: '16px' }}>expand_more</span>
              </div>
              {result.cleanup_status === 'processing' ? (
                <button className={actionBtn(false)} onClick={handleCancelCleanup}>
                  <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>stop_circle</span>Stop
                </button>
              ) : (
                <button className={actionBtn(true)} onClick={handleCleanup}>
                  <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>auto_awesome</span>
                  {result.cleanup_status === 'done' ? 'Re-run cleanup' : 'Clean with AI'}
                </button>
              )}
            </>
          )}

          {activeTab === 'summary' && (
            <>
              <div className="relative">
                <select
                  className="bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 pr-8 text-label-md focus:ring-2 focus:ring-primary/20 outline-none appearance-none cursor-pointer min-w-[180px]"
                  value={summaryModel}
                  onChange={e => handleSummaryModelChange(e.target.value)}
                  disabled={models.length === 0}
                  title={models.length === 0 ? 'Ollama offline — cannot load models' : 'Model for summarization'}
                >
                  <option value="">— summary model —</option>
                  {models.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
                <span className="material-symbols-outlined absolute right-2 top-2.5 text-secondary pointer-events-none" style={{ fontSize: '16px' }}>expand_more</span>
              </div>
              {result.summary_status === 'processing' ? (
                <button className={actionBtn(false)} onClick={handleCancelSummary}>
                  <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>stop_circle</span>Stop
                </button>
              ) : (
                <button className={actionBtn(true)} onClick={handleSummarize}>
                  <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>refresh</span>
                  {result.summary_status === 'done' ? 'Re-run summary' : 'Summarize'}
                </button>
              )}
              <a className={actionBtn(false)} href={`/benchmark/${result.video_id}`}>
                <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>balance</span>Benchmark
              </a>
            </>
          )}

          {/* Divider */}
          {activeTab !== 'chat' && <div className="h-8 w-px bg-outline-variant mx-1" />}

          {/* Common actions */}
          {activeTab !== 'chat' && (
            <>
              <button className={actionBtn(false)} onClick={handleCopy}>
                <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>content_copy</span>
                {copied ? 'Copied!' : 'Copy text'}
              </button>
              <a className={actionBtn(false)} href={result.url} target="_blank" rel="noreferrer">
                <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>open_in_new</span>
                Open video
              </a>
              <button className={actionBtn(false, true)} onClick={handleDelete}>
                <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>delete</span>
                Delete
              </button>
            </>
          )}

          {/* Mindmap + MD toggles — right side */}
          <div className="ml-auto flex items-center gap-2">
            {activeTab === 'summary' && result.summary_text && (
              <button
                className={`p-2 rounded text-label-sm font-bold transition-colors ${mindmapEnabled ? 'bg-primary text-on-primary' : 'bg-surface-container-high text-secondary hover:bg-surface-container-highest'}`}
                onClick={async () => {
                  if (!mindmapEnabled) {
                    setMindmapEnabled(true)
                    if (!result.mindmap_text && result.mindmap_status !== 'processing') await handleMindmap()
                  } else {
                    setMindmapEnabled(false)
                  }
                }}
                title={mindmapEnabled ? 'Mindmap ON — click to switch to text' : 'Text view — click to generate mindmap'}
              >🗺</button>
            )}
            <button
              className={`px-2.5 py-1.5 rounded text-label-sm font-bold border transition-colors ${markdownEnabled ? 'bg-primary/10 text-primary border-primary/20' : 'bg-surface-container-high text-secondary border-outline-variant hover:bg-surface-container-highest'}`}
              onClick={() => {
                const next = !markdownEnabled
                setMarkdownEnabled(next)
                localStorage.setItem('yt-md-enabled', String(next))
              }}
              title={markdownEnabled ? 'Markdown rendering ON — click to switch to plain text' : 'Plain text — click to enable Markdown rendering'}
            >MD</button>
          </div>
        </div>

        {/* Error banners */}
        {activeTab === 'cleaned' && (result.cleanup_status === 'failed' || cleanupError) && (
          <div className="mx-6 mt-4 bg-error-container text-on-error-container rounded-lg px-4 py-3 text-body-sm">
            {cleanupError || 'Cleanup failed. Possible causes: Ollama is not running, no model is selected, or the model returned no output. Check backend log for details.'}
          </div>
        )}
        {activeTab === 'summary' && (result.summary_status === 'failed' || summaryError) && (
          <div className="mx-6 mt-4 bg-error-container text-on-error-container rounded-lg px-4 py-3 text-body-sm">
            {summaryError || 'Summarization failed. Possible causes: Ollama is not running, no model is selected, or a stage timed out. Check backend log for details.'}
          </div>
        )}

        {/* Tabs bar */}
        <div className="px-6 border-b border-outline-variant">
          <div className="flex gap-6">
            <button className={tabClass('subtitles')} onClick={() => setActiveTab('subtitles')}>Subtitles</button>
            <button className={tabClass('cleaned')} onClick={() => setActiveTab('cleaned')}>
              {result.cleanup_status === 'processing'
                ? <span className="flex items-center gap-2"><span className="material-symbols-outlined" style={{ fontSize: '14px', animation: 'spin 1s linear infinite' }}>progress_activity</span>Cleaning…</span>
                : 'Cleaned'}
            </button>
            <button className={tabClass('summary')} onClick={() => setActiveTab('summary')}>
              {result.summary_status === 'processing'
                ? <span className="flex items-center gap-2"><span className="material-symbols-outlined" style={{ fontSize: '14px', animation: 'spin 1s linear infinite' }}>progress_activity</span>Summarizing…</span>
                : 'Summary'}
            </button>
            {chatHistory.length > 0 && (
              <button className={tabClass('chat')} onClick={() => setActiveTab('chat')}>
                Chat <span className="ml-1 text-[11px] bg-primary/10 text-primary px-1.5 py-0.5 rounded-full font-bold">{chatHistory.length}</span>
              </button>
            )}
          </div>
        </div>

        {/* Tab content */}
        <div className="p-6">
          {activeTab === 'summary' ? (
            !result.summary_text ? (
              <div className="py-12 text-center text-secondary text-body-md">
                {result.summary_status === 'processing'
                  ? 'Summarization is running…'
                  : result.summary_status === 'failed'
                    ? 'Summary failed. Click "Re-run summary" to try again.'
                    : 'No summary yet. Click "Summarize" above to generate one.'}
              </div>
            ) : mindmapEnabled ? (
              result.mindmap_status === 'processing' ? (
                <div className="py-12 flex items-center justify-center gap-4 text-secondary text-body-md">
                  <span className="material-symbols-outlined" style={{ animation: 'spin 1s linear infinite' }}>progress_activity</span>
                  Generating mindmap…
                  <button
                    className="ml-4 text-error hover:underline text-label-md"
                    onClick={async () => {
                      await cancelMindmap(videoId!)
                      stopMindmapPolling()
                      setResult(r => r ? { ...r, mindmap_status: null } : r)
                    }}
                  >Stop</button>
                </div>
              ) : result.mindmap_status === 'failed' || mindmapError ? (
                <div className="bg-error-container text-on-error-container rounded-lg px-4 py-3 text-body-sm">
                  {mindmapError || 'Mindmap generation failed. Check that Ollama is running and a model is selected.'}
                </div>
              ) : result.mindmap_text ? (
                <Suspense fallback={<div className="py-8 text-center text-secondary">Loading…</div>}>
                  <MindmapView text={result.mindmap_text} title={result.title ?? undefined} onRegenerate={() => handleMindmap(true)} />
                </Suspense>
              ) : (
                <div className="py-8 text-center text-secondary">Generating mindmap…</div>
              )
            ) : (
              <div className="text-on-surface text-body-md leading-relaxed">
                {markdownEnabled
                  ? <MarkdownContent text={result.summary_text!} />
                  : <div className="formatted-text">{renderText(result.summary_text!)}</div>
                }
                <div className="h-20" />
              </div>
            )
          ) : activeTab === 'chat' ? (
            <>
              {/* Chat header */}
              <div className="flex items-center gap-3 mb-4 pb-4 border-b border-outline-variant">
                <button className="text-label-md text-secondary hover:text-on-surface flex items-center gap-1.5 transition-colors" onClick={() => {
                  const text = chatHistory.filter(m => m.content).map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`).join('\n\n')
                  navigator.clipboard.writeText(text)
                }}>
                  <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>content_copy</span>Copy chat
                </button>
                <button className="text-label-md text-error hover:text-error/80 flex items-center gap-1.5 transition-colors" onClick={handleClearChat}>
                  <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>delete</span>Clear chat
                </button>
              </div>
              {/* Chat messages */}
              <div className="space-y-4">
                {chatHistory.map((msg, i) => (
                  <div key={i} className={`flex gap-3 group ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[85%] rounded-xl px-4 py-3 text-body-sm relative ${
                      msg.role === 'user'
                        ? 'bg-primary-container text-on-primary-container ml-12'
                        : 'bg-surface-container-low text-on-surface border border-outline-variant mr-12'
                    }`}>
                      {msg.content
                        ? (markdownEnabled && msg.role === 'assistant'
                            ? <ReactMarkdown>{msg.content}</ReactMarkdown>
                            : msg.content)
                        : (msg.role === 'assistant' && isChatting
                            ? <span className="flex gap-1 py-1">{[0,1,2].map(j => <span key={j} className="w-2 h-2 rounded-full bg-secondary animate-bounce" style={{ animationDelay: `${j * 0.15}s` }} />)}</span>
                            : null)}
                      {msg.content && (
                        <div className="opacity-0 group-hover:opacity-100 transition-opacity absolute -bottom-6 right-0 flex gap-1">
                          <button className="p-1 text-secondary hover:text-on-surface" onClick={() => navigator.clipboard.writeText(msg.content)} title="Copy">
                            <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>content_copy</span>
                          </button>
                          <button className="p-1 text-secondary hover:text-error transition-colors" onClick={() => deleteChatMessage(i)} title="Delete">
                            <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>delete</span>
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                <div ref={chatEndRef} />
              </div>
              <div className="h-20" />
            </>
          ) : activeTab === 'cleaned' && !result.cleaned_text ? (
            <div className="py-12 text-center text-secondary text-body-md">
              {result.cleanup_status === 'processing'
                ? 'AI cleanup is running…'
                : result.cleanup_status === 'failed'
                  ? 'Cleanup failed. Click "Re-run cleanup" to try again.'
                  : 'No cleaned version yet. Click "Clean with AI" above to start.'}
            </div>
          ) : (
            displayText
              ? markdownEnabled
                ? <MarkdownContent text={displayText} />
                : <div className="formatted-text">{renderText(displayText)}</div>
              : null
          )}
        </div>
      </section>

      {/* ── Fixed chat input bar ── */}
      {(activeTab === 'summary' || activeTab === 'chat') && result.summary_status === 'done' && result.summary_text && ollamaUrl && summaryModel && (
        <div className="fixed bottom-0 left-0 right-0 md:left-64 p-4 md:p-6 bg-surface-container-lowest/80 backdrop-blur-md border-t border-outline-variant z-50">
          {(() => {
            const sourceLen = (result.cleaned_text ?? result.formatted_text ?? '').length
            return sourceLen > CHAT_WARN_CHARS ? (
              <div className="max-w-[1200px] mx-auto mb-2 text-label-sm text-secondary">
                ⚠ Text is very long ({Math.round(sourceLen / 1000)}K chars) — response quality may vary
              </div>
            ) : null
          })()}
          <div className="max-w-[1200px] mx-auto">
            {chatHistory.length === 0 && (
              <div className="text-label-sm text-secondary bg-surface-container-low px-3 py-1 rounded-t-lg border-x border-t border-outline-variant w-fit">
                Ask a follow-up question about the video
              </div>
            )}
            <div className="flex items-center gap-3 bg-surface-container-lowest border-2 border-outline-variant rounded-full p-2 pl-5 pr-2 shadow-sm focus-within:border-primary/40 transition-all">
              <textarea
                ref={chatInputRef}
                className="flex-1 bg-transparent border-none focus:ring-0 outline-none text-body-md text-on-surface placeholder:text-secondary/60 resize-none leading-normal"
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
                className="w-10 h-10 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center hover:scale-105 active:scale-95 transition-transform disabled:opacity-40"
                onClick={sendChatMessage}
                disabled={isChatting || !chatInput.trim()}
                title="Send"
              >
                {isChatting
                  ? <span className="material-symbols-outlined" style={{ fontSize: '18px', animation: 'spin 1s linear infinite' }}>progress_activity</span>
                  : <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>send</span>
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
