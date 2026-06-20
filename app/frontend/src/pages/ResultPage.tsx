import { useEffect, useRef, useState, lazy, Suspense } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  getResult, deleteResult,
  cancelCleanup, startSummary,
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
  const dd  = String(d.getDate()).padStart(2, '0')
  const mm  = String(d.getMonth() + 1).padStart(2, '0')
  const yyyy = d.getFullYear()
  const hh  = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${dd}.${mm}.${yyyy}, ${hh}:${min}`
}

function MetaDot() {
  return <span className="w-1 h-1 rounded-full bg-outline-variant flex-shrink-0" />
}

export default function ResultPage() {
  const { videoId } = useParams<{ videoId: string }>()
  const navigate = useNavigate()
  const [result, setResult]             = useState<ResultResponse | null>(null)
  const [error, setError]               = useState('')
  const [cleanupError, setCleanupError] = useState('')
  const [summaryError, setSummaryError] = useState('')
  const [copied, setCopied]             = useState(false)
  const [activeTab, setActiveTab]       = useState<Tab>('subtitles')
  const [markdownEnabled, setMarkdownEnabled] = useState(() =>
    localStorage.getItem('yt-md-enabled') === 'true'
  )
  const [mindmapEnabled, setMindmapEnabled] = useState(false)
  const [mindmapError, setMindmapError]     = useState('')
  const mindmapPollRef          = useRef<ReturnType<typeof setInterval> | null>(null)
  const prevMindmapStatusRef    = useRef<string | null | undefined>(undefined)
  const [reextractLang, setReextractLang] = useState('auto')
  const [cleanupModel, setCleanupModel]   = useState('')
  const [summaryModel, setSummaryModel]   = useState('')
  const [models, setModels]               = useState<string[]>([])
  const [cleanupElapsedSeconds, setCleanupElapsedSeconds] = useState<number | null>(null)
  const [summaryElapsedSeconds, setSummaryElapsedSeconds] = useState<number | null>(null)
  const [localCleanupDuration, setLocalCleanupDuration]   = useState<number | null>(null)
  const [localSummaryDuration, setLocalSummaryDuration]   = useState<number | null>(null)

  // Chat
  const [ollamaUrl, setOllamaUrl]   = useState('')
  const [chatHistory, setChatHistory] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([])
  const [chatInput, setChatInput]     = useState('')
  const [isChatting, setIsChatting]   = useState(false)
  const [chatCopied, setChatCopied]   = useState(false)
  const ollamaMessagesRef    = useRef<Array<{ role: string; content: string }>>([])
  const chatEndRef           = useRef<HTMLDivElement>(null)
  const chatInputRef         = useRef<HTMLTextAreaElement>(null)
  const chatHistoryLoadedRef = useRef(false)
  const autoSummarizeAfterCleanupRef = useRef(false)
  const [queuedMsg, setQueuedMsg] = useState<string | null>(null)
  const CHAT_WARN_CHARS = 100_000

  // Notifications
  const originalTitleRef = useRef(document.title)

  function requestNotifyPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }

  function notify(title: string, body?: string) {
    document.title = `✓ ${title}`
    setTimeout(() => { document.title = originalTitleRef.current }, 10_000)
    if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
      new Notification(title, { body, icon: '/favicon.ico' })
    }
  }

  const pollRef           = useRef<ReturnType<typeof setInterval> | null>(null)
  const summaryPollRef    = useRef<ReturnType<typeof setInterval> | null>(null)
  const cleanupTimerRef   = useRef<ReturnType<typeof setInterval> | null>(null)
  const summaryTimerRef   = useRef<ReturnType<typeof setInterval> | null>(null)
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

  function stopPolling()         { if (pollRef.current)        { clearInterval(pollRef.current);        pollRef.current = null } }
  function stopSummaryPolling()  { if (summaryPollRef.current) { clearInterval(summaryPollRef.current); summaryPollRef.current = null } }
  function stopMindmapPolling()  { if (mindmapPollRef.current) { clearInterval(mindmapPollRef.current); mindmapPollRef.current = null } }
  function stopCleanupTimer()    { if (cleanupTimerRef.current) { clearInterval(cleanupTimerRef.current); cleanupTimerRef.current = null } }
  function stopSummaryTimer()    { if (summaryTimerRef.current) { clearInterval(summaryTimerRef.current); summaryTimerRef.current = null } }

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
        prevMindmapStatusRef.current = data.mindmap_status
        setResult(data)

        if (!chatHistoryLoadedRef.current) {
          chatHistoryLoadedRef.current = true
          if (data.chat_history && data.chat_history.length > 0) {
            setChatHistory(data.chat_history as Array<{ role: 'user' | 'assistant'; content: string }>)
          }
        }

        if (switchTab) {
          if (data.summary_status === 'done') setActiveTab('summary')
          else if (data.cleanup_status === 'done') setActiveTab('cleaned')
          else setActiveTab('subtitles')
        } else {
          if (prevCleanup === 'processing' && data.cleanup_status === 'done') {
            notify('AI Cleanup complete', data.title ?? undefined)
            if (autoSummarizeAfterCleanupRef.current) {
              autoSummarizeAfterCleanupRef.current = false
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

        if (data.cleanup_status !== 'processing') {
          if (prevCleanup === 'processing' && data.cleanup_status === 'done' && data.cleanup_duration_seconds == null) {
            setLocalCleanupDuration(cleanupElapsedRef.current)
          } else if (data.cleanup_duration_seconds != null) {
            setLocalCleanupDuration(null)
          }
          stopPolling(); stopCleanupTimer(); setCleanupElapsedSeconds(null)
        } else if (!cleanupTimerRef.current) {
          startCleanupTimer()
        }

        if (data.mindmap_status !== 'processing') {
          stopMindmapPolling()
        } else if (!mindmapPollRef.current) {
          mindmapPollRef.current = setInterval(() => loadResult(false), 3000)
        }

        if (data.summary_status !== 'processing') {
          if (prevSummary === 'processing' && data.summary_status === 'done' && data.summary_duration_seconds == null) {
            setLocalSummaryDuration(summaryElapsedRef.current)
          } else if (data.summary_duration_seconds != null) {
            setLocalSummaryDuration(null)
          }
          stopSummaryPolling(); stopSummaryTimer(); setSummaryElapsedSeconds(null)
        } else if (!summaryTimerRef.current) {
          startSummaryTimer()
        }
      })
      .catch(err => { console.error('[Result] getResult failed:', err); setError('Could not load result') })
  }

  useEffect(() => {
    loadResult(true)
    return () => { stopPolling(); stopSummaryPolling(); stopMindmapPolling(); stopCleanupTimer(); stopSummaryTimer() }
  }, [videoId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!result?.reextract_in_progress) return
    const id = setInterval(() => loadResult(), 3000)
    return () => clearInterval(id)
  }, [result?.reextract_in_progress]) // eslint-disable-line react-hooks/exhaustive-deps

  function loadSettings() {
    Promise.all([getSettings(), getModels()])
      .then(([s, list]) => {
        setCleanupModel(s.cleanup.model ?? '')
        setSummaryModel(s.summarization.model ?? '')
        setOllamaUrl(s.app.ollama_url ?? '')
        setModels(list)
        cleanupPromptsRef.current = { system_prompt: s.cleanup.system_prompt ?? null, user_prompt_template: s.cleanup.user_prompt_template ?? null }
        summaryPromptsRef.current = { system_prompt: s.summarization.system_prompt ?? null, user_prompt_template: s.summarization.user_prompt_template ?? null }
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
      if (document.visibilityState === 'visible') { loadSettings(); document.title = originalTitleRef.current }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (result?.cleanup_status === 'processing' && !pollRef.current) {
      pollRef.current = setInterval(() => loadResult(false), 3000)
    }
  }, [result?.cleanup_status]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (result?.summary_status === 'processing' && !summaryPollRef.current) {
      summaryPollRef.current = setInterval(() => loadResult(false), 3000)
    }
  }, [result?.summary_status]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatHistory])

  async function sendChatMessage() {
    const question = chatInput.trim()
    if (!question || isChatting || !ollamaUrl || !summaryModel || !result) return

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

      const reader  = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer    = ''

      const processLine = (line: string) => {
        if (!line.trim()) return
        try {
          const json  = JSON.parse(line)
          const token = json.message?.content ?? json.response ?? ''
          if (token) {
            fullResponse += token
            setChatHistory(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = { role: 'assistant', content: fullResponse }
              return updated
            })
          }
        } catch { /* skip malformed */ }
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
    navigator.clipboard.writeText(lines).then(() => { setChatCopied(true); setTimeout(() => setChatCopied(false), 2000) })
  }

  const displayText =
    activeTab === 'summary' ? result?.summary_text :
    activeTab === 'cleaned' ? (result?.cleaned_text ?? result?.formatted_text) :
    activeTab === 'chat'    ? null :
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
    try { await cancelCleanup(videoId) } catch (err) { console.error('[Result] cancelCleanup failed:', err) }
    setCleanupElapsedSeconds(null); cleanupElapsedRef.current = null; setLocalCleanupDuration(null)
    setResult(prev => prev ? { ...prev, cleanup_status: null, cleaned_text: null, cleanup_duration_seconds: null } : prev)
  }

  async function handleCancelSummary() {
    if (!videoId) return
    stopSummaryPolling(); stopSummaryTimer()
    try { await cancelSummary(videoId) } catch (err) { console.error('[Result] cancelSummary failed:', err) }
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
      setResult(prev => prev ? { ...prev, reextract_in_progress: true } : prev)
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
    if (!result.cleanup_status && !result.cleaned_text) {
      const confirmed = window.confirm(
        'AI Cleanup has not been run yet.\n\nTo get a quality summary, cleanup should run first.\n\nRun cleanup → summarize pipeline now?'
      )
      if (!confirmed) return
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
      if (force) setResult(r => r ? { ...r, mindmap_text: null, mindmap_status: null } : r)
      await queueBulkAdd([result.url], ['mindmap'])
      setQueuedMsg('mindmap')
      stopMindmapPolling()
      mindmapPollRef.current = setInterval(() => loadResult(false), 3000)
    } catch (err: unknown) {
      console.error('[Mindmap] failed:', err)
      setMindmapError(err instanceof Error ? err.message : 'Unknown error')
    }
  }

  // ── Error / loading states ──────────────────────────────────────────────────
  if (error) return (
    <div className="p-8 max-w-[1200px] mx-auto">
      <div className="bg-error-container rounded-xl p-6 text-on-error-container text-body-md">{error}</div>
    </div>
  )
  if (!result) return (
    <div className="flex items-center justify-center p-16">
      <span className="material-symbols-outlined text-secondary pulse-dot" style={{ fontSize: 32 }}>hourglass_top</span>
    </div>
  )

  // ── Derived values ──────────────────────────────────────────────────────────
  const cleanupDuration  = result.cleanup_duration_seconds ?? localCleanupDuration
  const summaryDuration  = result.summary_duration_seconds ?? localSummaryDuration
  const chatBarVisible   = (activeTab === 'summary' || activeTab === 'chat')
    && result.summary_status === 'done' && !!result.summary_text && !!ollamaUrl && !!summaryModel

  const subtitlesCount = result.char_count ?? result.formatted_text?.length ?? null
  const cleanedCount   = result.cleaned_text?.length ?? null
  const summaryCount   = result.summary_text?.length ?? null
  const displayCharCount =
    activeTab === 'summary' ? summaryCount :
    activeTab === 'cleaned' ? cleanedCount : subtitlesCount

  const selectCls = 'bg-surface-container-low border border-outline-variant rounded-lg px-4 py-2 text-label-md focus:ring-2 focus:ring-primary/20 outline-none appearance-none disabled:opacity-50'
  const btnSecondary = 'flex items-center gap-2 px-5 py-2 bg-surface-container-lowest text-secondary border border-outline-variant rounded-lg text-label-md font-medium hover:bg-surface-container-low active:scale-[0.98] transition-all'
  const btnDanger    = 'flex items-center gap-2 px-5 py-2 text-error border border-error/30 rounded-lg text-label-md font-medium hover:bg-error/5 active:scale-[0.98] transition-all'
  const btnAi        = 'flex items-center gap-2 px-5 py-2 bg-primary-container text-on-primary-container rounded-lg text-label-md font-medium hover:opacity-90 active:scale-[0.98] transition-all shadow-sm'

  return (
    <>
      <div className={`p-6 md:p-8 max-w-[1200px] mx-auto${chatBarVisible ? ' pb-36' : ''}`}>
        <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm overflow-hidden">

          {/* ── Card header: title + star ── */}
          <div className="p-6 border-b border-outline-variant">
            <div className="flex justify-between items-start mb-4 gap-3">
              <h2 className="text-headline-xl font-bold text-on-surface flex-1 leading-tight">
                {result.title ?? 'Untitled'}
              </h2>
              <button
                onClick={async () => {
                  const r = await toggleFavorite(videoId!)
                  setResult(prev => prev ? { ...prev, is_favorite: r.is_favorite } : prev)
                }}
                title={result.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
                className="material-symbols-outlined text-[28px] transition-colors flex-shrink-0 focus:outline-none"
                style={{
                  fontVariationSettings: result.is_favorite ? "'FILL' 1" : "'FILL' 0",
                  color: result.is_favorite ? '#f59e0b' : undefined,
                }}
              >star</button>
            </div>

            {/* Meta row */}
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-secondary text-body-sm">
              {result.author && (
                <div><span className="font-semibold text-on-surface">Channel:</span> {result.author}</div>
              )}
              <div><span className="font-semibold text-on-surface">Duration:</span> {formatDuration(result.duration)}</div>
              {result.language && (
                <div><span className="font-semibold text-on-surface">Language:</span> {result.language.toUpperCase()}</div>
              )}
              {displayCharCount != null && (
                <div><span className="font-semibold text-on-surface">Characters:</span> {displayCharCount.toLocaleString()}</div>
              )}
              <div><span className="font-semibold text-on-surface">Saved:</span> {formatDate(result.created_at)}</div>
            </div>
          </div>

          {/* ── Meta ribbon: cleanup processing ── */}
          {activeTab === 'cleaned' && result.cleanup_status === 'processing' && cleanupElapsedSeconds != null && (
            <div className="px-6 py-3 bg-surface-container-low border-b border-outline-variant flex flex-wrap items-center gap-3 text-label-sm text-secondary">
              <span className="material-symbols-outlined text-[16px] pulse-dot">sync</span>
              Cleaning {formatDuration(cleanupElapsedSeconds)}
              {result.cleanup_paragraphs_done != null && result.cleanup_paragraphs_total != null && (
                <><MetaDot />paragraph {result.cleanup_paragraphs_done} / {result.cleanup_paragraphs_total}</>
              )}
            </div>
          )}

          {/* ── Meta ribbon: cleanup done ── */}
          {activeTab === 'cleaned' && result.cleanup_status !== 'processing' && cleanupDuration != null && (
            <div className="px-6 py-3 bg-surface-container-low border-b border-outline-variant flex flex-wrap items-center gap-3 text-label-sm text-secondary">
              <span className="material-symbols-outlined text-[16px]">timer</span>
              Cleaned in {formatDuration(cleanupDuration)}
              {result.cleanup_model && (
                <><MetaDot /><span className="font-bold text-on-surface">{result.cleanup_model}</span></>
              )}
              <MetaDot />
              <span className="px-2 py-0.5 rounded-full bg-primary-container/20 text-primary font-bold text-tag-uppercase">AI Cleanup</span>
              {(() => {
                const count = result.cleaned_text ? result.cleaned_text.split('\n\n').filter(p => p.trim()).length : null
                return count != null ? <><MetaDot />{count} paragraphs</> : null
              })()}
              {result.cleanup_finished_at && (
                <><MetaDot />{formatDate(result.cleanup_finished_at)}</>
              )}
            </div>
          )}

          {/* ── Meta ribbon: summary processing ── */}
          {activeTab === 'summary' && result.summary_status === 'processing' && summaryElapsedSeconds != null && (
            <div className="px-6 py-3 bg-surface-container-low border-b border-outline-variant flex flex-wrap items-center gap-3 text-label-sm text-secondary">
              <span className="material-symbols-outlined text-[16px] pulse-dot">sync</span>
              Summarizing {formatDuration(summaryElapsedSeconds)}
              {result.summary_chunks_done != null && result.summary_chunks_total != null && (
                <><MetaDot />{result.chapters ? 'chapter' : 'chunk'} {result.summary_chunks_done} / {result.summary_chunks_total}</>
              )}
            </div>
          )}

          {/* ── Meta ribbon: summary done ── */}
          {activeTab === 'summary' && result.summary_status !== 'processing' && summaryDuration != null && (
            <div className="px-6 py-3 bg-surface-container-low border-b border-outline-variant flex flex-wrap items-center gap-3 text-label-sm text-secondary">
              <span className="material-symbols-outlined text-[16px]">timer</span>
              Summarized in {formatDuration(summaryDuration)}
              {result.summary_model && (
                <><MetaDot /><span className="font-bold text-on-surface">{result.summary_model}</span></>
              )}
              {result.summary_mode === 'single' && (
                <><MetaDot /><span className="px-2 py-0.5 rounded-full bg-primary-container/20 text-primary font-bold text-tag-uppercase">Single Pass</span></>
              )}
              {result.summary_mode === 'map_reduce' && (
                <>
                  <MetaDot /><span className="px-2 py-0.5 rounded-full bg-primary-container/20 text-primary font-bold text-tag-uppercase">Map-Reduce</span>
                  {result.summary_chunks_count != null && <><MetaDot />{result.summary_chunks_count} chunks</>}
                </>
              )}
              {result.summary_mode === 'full_extract' && (
                <>
                  <MetaDot /><span className="px-2 py-0.5 rounded-full bg-primary-container/20 text-primary font-bold text-tag-uppercase">Full Extract</span>
                  {result.summary_chunks_count != null && <><MetaDot />{result.summary_chunks_count} chapters</>}
                </>
              )}
              {(() => {
                const inputLen  = result.cleaned_text?.length ?? result.formatted_text?.length ?? null
                const outputLen = result.summary_text?.length ?? null
                if (!inputLen || !outputLen || outputLen >= inputLen) return null
                const pct = Math.round((1 - outputLen / inputLen) * 100)
                return <><MetaDot />{pct}% compressed</>
              })()}
              {result.summary_finished_at && (
                <><MetaDot />{formatDate(result.summary_finished_at)}</>
              )}
            </div>
          )}

          {/* ── Queue message ── */}
          {queuedMsg && (
            <div className="px-6 py-3 border-b border-tertiary/20 bg-tertiary-container/10 flex items-center gap-2">
              <span className="material-symbols-outlined text-tertiary text-[18px]">schedule</span>
              <span className="text-body-sm text-on-surface">
                Added to queue{' '}
                {queuedMsg === 'cleanup+summary' ? '(cleanup → summary)' : queuedMsg === 'cleanup' ? '(cleanup)' : queuedMsg === 'summary' ? '(summary)' : '(mindmap)'}
                {' · '}
                <Link to="/queue" className="text-primary font-semibold underline">View queue →</Link>
              </span>
              <button onClick={() => setQueuedMsg(null)} className="ml-auto material-symbols-outlined text-[18px] text-secondary hover:text-on-surface transition-colors">close</button>
            </div>
          )}

          {/* ── Controls + Tabs ── */}
          <div className="p-6 space-y-5">

            {/* Action buttons */}
            <div className="flex flex-wrap items-center gap-3">

              {/* Subtitles tab controls */}
              {activeTab === 'subtitles' && (
                <>
                  <select
                    value={reextractLang}
                    onChange={e => setReextractLang(e.target.value)}
                    disabled={!!result.reextract_in_progress}
                    className={`${selectCls} min-w-[120px]`}
                  >
                    <option value="auto">Auto</option>
                    <option value="ru">Russian</option>
                    <option value="en">English</option>
                    <option value="uk">Ukrainian</option>
                  </select>
                  <button
                    onClick={handleReextract}
                    disabled={!!result.reextract_in_progress || result.cleanup_status === 'processing' || result.summary_status === 'processing'}
                    className={`${btnSecondary} disabled:opacity-50`}
                    title="Re-fetch subtitles from YouTube. Cleanup and Summary will be cleared."
                  >
                    <span className="material-symbols-outlined text-[18px]">refresh</span>
                    {result.reextract_in_progress ? 'Re-extracting…' : 'Re-extract'}
                  </button>
                </>
              )}

              {/* Cleaned tab controls */}
              {activeTab === 'cleaned' && (
                <>
                  <div className="relative min-w-[180px]">
                    <select
                      value={cleanupModel}
                      onChange={e => handleCleanupModelChange(e.target.value)}
                      disabled={models.length === 0}
                      title={models.length === 0 ? 'Ollama offline' : 'Model for AI cleanup'}
                      className={`${selectCls} w-full pr-8`}
                    >
                      <option value="">— cleanup model —</option>
                      {models.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                    <span className="material-symbols-outlined absolute right-2 top-2.5 text-secondary pointer-events-none text-[16px]">expand_more</span>
                  </div>
                  {result.cleanup_status === 'processing' ? (
                    <button onClick={handleCancelCleanup} className={btnSecondary}>
                      <span className="material-symbols-outlined text-[18px]">stop_circle</span>Stop
                    </button>
                  ) : (
                    <button onClick={handleCleanup} className={btnAi}>
                      <span className="material-symbols-outlined text-[18px]">auto_awesome</span>
                      {result.cleanup_status === 'done' ? 'Re-run AI cleanup' : 'Clean with AI'}
                    </button>
                  )}
                </>
              )}

              {/* Summary tab controls */}
              {activeTab === 'summary' && (
                <>
                  <div className="relative min-w-[180px]">
                    <select
                      value={summaryModel}
                      onChange={e => handleSummaryModelChange(e.target.value)}
                      disabled={models.length === 0}
                      title={models.length === 0 ? 'Ollama offline' : 'Model for summarization'}
                      className={`${selectCls} w-full pr-8`}
                    >
                      <option value="">— summary model —</option>
                      {models.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                    <span className="material-symbols-outlined absolute right-2 top-2.5 text-secondary pointer-events-none text-[16px]">expand_more</span>
                  </div>
                  {result.summary_status === 'processing' ? (
                    <button onClick={handleCancelSummary} className={btnSecondary}>
                      <span className="material-symbols-outlined text-[18px]">stop_circle</span>Stop
                    </button>
                  ) : (
                    <button onClick={handleSummarize} className={btnAi}>
                      <span className="material-symbols-outlined text-[18px]">auto_awesome</span>
                      {result.summary_status === 'done' ? 'Re-run summary' : 'Summarize'}
                    </button>
                  )}
                </>
              )}

              {/* Benchmark (all tabs except chat) */}
              {activeTab !== 'chat' && (
                <a href={`/benchmark/${result.video_id}`} className={btnSecondary}>
                  <span className="material-symbols-outlined text-[18px]">balance</span>Benchmark
                </a>
              )}

              {/* Divider */}
              {activeTab !== 'chat' && <div className="h-8 w-px bg-outline-variant mx-1" />}

              {/* Copy / chat-specific actions */}
              {activeTab === 'chat' ? (
                chatHistory.length > 0 && (
                  <>
                    <button onClick={copyChat} className={btnSecondary}>
                      <span className="material-symbols-outlined text-[18px]">content_copy</span>
                      {chatCopied ? 'Copied!' : 'Copy chat'}
                    </button>
                    <button onClick={handleClearChat} className={btnDanger}>
                      <span className="material-symbols-outlined text-[18px]">delete</span>Clear chat
                    </button>
                  </>
                )
              ) : (
                displayText && (
                  <button onClick={handleCopy} className={btnSecondary}>
                    <span className="material-symbols-outlined text-[18px]">content_copy</span>
                    {copied ? 'Copied!' : 'Copy text'}
                  </button>
                )
              )}

              {/* Open video */}
              <a href={result.url} target="_blank" rel="noreferrer" className={btnSecondary}>
                <span className="material-symbols-outlined text-[18px]">open_in_new</span>Open video
              </a>

              {/* Delete */}
              <button onClick={handleDelete} className={btnDanger}>
                <span className="material-symbols-outlined text-[18px]">delete</span>Delete
              </button>
            </div>

            {/* Error banners */}
            {activeTab === 'cleaned' && (result.cleanup_status === 'failed' || cleanupError) && (
              <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3">
                <p className="text-body-sm text-on-error-container">
                  {cleanupError || 'Cleanup failed. Possible causes: Ollama not running, no model selected, or model timed out on large paragraphs. Check backend log.'}
                </p>
              </div>
            )}
            {activeTab === 'summary' && (result.summary_status === 'failed' || summaryError) && (
              <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3">
                <p className="text-body-sm text-on-error-container">
                  {summaryError || 'Summarization failed. Possible causes: Ollama not running, no model selected, or a stage timed out. For very long texts try a stronger model or wait for hierarchical map-reduce.'}
                </p>
              </div>
            )}

            {/* Tabs bar */}
            <div className="-mx-6 px-6 border-b border-outline-variant">
              <div className="flex items-end gap-8">
                {(['subtitles', 'cleaned', 'summary'] as Tab[]).map(tab => {
                  const isActive = activeTab === tab
                  const isProcessing =
                    (tab === 'cleaned'  && result.cleanup_status === 'processing') ||
                    (tab === 'summary'  && result.summary_status === 'processing')
                  const label =
                    tab === 'subtitles' ? 'Subtitles' :
                    tab === 'cleaned'   ? 'Cleaned'   : 'Summary'
                  return (
                    <button
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      className={`pb-3 text-label-md font-medium transition-colors flex items-center gap-1.5 ${
                        isActive ? 'text-primary font-bold border-b-2 border-primary' : 'text-secondary hover:text-on-surface'
                      }`}
                    >
                      {isProcessing && (
                        <span className="material-symbols-outlined text-[12px] pulse-dot">sync</span>
                      )}
                      {label}
                      {isProcessing && <span className="text-[11px]">…</span>}
                    </button>
                  )
                })}
                {chatHistory.length > 0 && (
                  <button
                    onClick={() => setActiveTab('chat')}
                    className={`pb-3 text-label-md font-medium transition-colors ${
                      activeTab === 'chat' ? 'text-primary font-bold border-b-2 border-primary' : 'text-secondary hover:text-on-surface'
                    }`}
                  >
                    Chat <span className="text-[11px]">({chatHistory.length})</span>
                  </button>
                )}

                {/* Right side toggles */}
                <div className="ml-auto flex items-center gap-2 pb-2">
                  {activeTab === 'summary' && result.summary_text && (
                    <button
                      onClick={async () => {
                        if (!mindmapEnabled) {
                          setMindmapEnabled(true)
                          if (!result.mindmap_text && result.mindmap_status !== 'processing') await handleMindmap()
                        } else {
                          setMindmapEnabled(false)
                        }
                      }}
                      title={mindmapEnabled ? 'Mindmap ON — click for text' : 'Text view — click for mindmap'}
                      className={`px-3 py-1 rounded border text-label-sm font-bold transition-colors ${mindmapEnabled ? 'bg-primary text-on-primary border-primary' : 'border-outline-variant text-secondary hover:bg-surface-container-high'}`}
                    >🗺</button>
                  )}
                  <button
                    onClick={() => {
                      const next = !markdownEnabled
                      setMarkdownEnabled(next)
                      localStorage.setItem('yt-md-enabled', String(next))
                    }}
                    title={markdownEnabled ? 'Markdown ON — click for plain text' : 'Click to enable Markdown rendering'}
                    className={`px-3 py-1 rounded border text-[10px] font-bold tracking-wider transition-colors ${markdownEnabled ? 'bg-primary text-on-primary border-primary' : 'border-outline-variant text-secondary hover:bg-surface-container-high'}`}
                  >MD</button>
                </div>
              </div>
            </div>
          </div>

          {/* ── Tab content ── */}
          <div className="px-6 pb-8">
            {activeTab === 'summary' ? (
              !result.summary_text ? (
                <div className="py-12 text-center text-secondary text-body-md">
                  {result.summary_status === 'processing' ? 'Summarization is running…'
                    : result.summary_status === 'failed' ? 'Summary failed. Click "Re-run summary" to try again.'
                    : 'No summary yet. Click "Summarize" above to generate one.'}
                </div>
              ) : mindmapEnabled ? (
                result.mindmap_status === 'processing' ? (
                  <div className="py-12 flex items-center justify-center gap-3 text-secondary text-body-md">
                    <span className="material-symbols-outlined pulse-dot">account_tree</span>
                    Generating mindmap…
                    <button
                      onClick={async () => {
                        await cancelMindmap(videoId!)
                        stopMindmapPolling()
                        setResult(r => r ? { ...r, mindmap_status: null } : r)
                      }}
                      className="ml-4 flex items-center gap-1 text-error border border-error/30 px-3 py-1.5 rounded-lg text-label-sm hover:bg-error/5 transition-colors"
                    >
                      <span className="material-symbols-outlined text-[16px]">stop_circle</span>Stop
                    </button>
                  </div>
                ) : result.mindmap_status === 'failed' || mindmapError ? (
                  <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3 text-on-error-container text-body-sm">
                    {mindmapError || 'Mindmap generation failed. Check Ollama and model settings.'}
                  </div>
                ) : result.mindmap_text ? (
                  <Suspense fallback={<div className="py-8 text-center text-secondary text-body-md">Loading…</div>}>
                    <MindmapView text={result.mindmap_text} title={result.title ?? undefined} onRegenerate={() => handleMindmap(true)} />
                  </Suspense>
                ) : (
                  <div className="py-12 text-center text-secondary text-body-md">Generating mindmap…</div>
                )
              ) : (
                <>
                  {markdownEnabled ? <MarkdownContent text={result.summary_text!} /> : <div className="formatted-text">{renderText(result.summary_text!)}</div>}
                  {chatBarVisible && <div className="h-20" />}
                </>
              )
            ) : activeTab === 'chat' ? (
              chatHistory.length === 0 ? (
                <div className="py-12 text-center text-secondary text-body-md">
                  No chat history. Ask a question in the input bar below.
                </div>
              ) : (
                <>
                  <div className="chat-thread">
                    {chatHistory.map((msg, i) => (
                      <div key={i} className={`chat-msg chat-msg--${msg.role}`}>
                        {msg.content
                          ? (markdownEnabled && msg.role === 'assistant'
                              ? <ReactMarkdown>{msg.content}</ReactMarkdown>
                              : msg.content)
                          : (msg.role === 'assistant' && isChatting
                              ? <span className="chat-typing"><span className="chat-typing-dot" /><span className="chat-typing-dot" /><span className="chat-typing-dot" /></span>
                              : null)}
                        {msg.content && (
                          <>
                            <button className="chat-msg-copy" onClick={() => navigator.clipboard.writeText(msg.content)} title="Copy message">⎘</button>
                            <button className="chat-msg-copy chat-msg-delete" onClick={() => deleteChatMessage(i)} title="Delete message">🗑</button>
                          </>
                        )}
                      </div>
                    ))}
                    <div ref={chatEndRef} />
                  </div>
                  {chatBarVisible && <div className="h-20" />}
                </>
              )
            ) : activeTab === 'cleaned' && !result.cleaned_text ? (
              <div className="py-12 text-center text-secondary text-body-md">
                {result.cleanup_status === 'processing' ? 'AI cleanup is running…'
                  : result.cleanup_status === 'failed' ? 'Cleanup failed. Click "Re-run AI cleanup" to try again.'
                  : 'No cleaned version yet. Click "Clean with AI" above to start.'}
              </div>
            ) : (
              displayText
                ? markdownEnabled ? <MarkdownContent text={displayText} /> : <div className="formatted-text">{renderText(displayText)}</div>
                : null
            )}
          </div>
        </div>
      </div>

      {/* ── Fixed chat input bar ── */}
      {chatBarVisible && (
        <div className="fixed bottom-0 left-0 right-0 md:left-64 z-30 px-6 py-4 bg-white/90 backdrop-blur-md border-t border-outline-variant dark:bg-surface-container-low/90">
          <div className="max-w-[1200px] mx-auto space-y-2">
            {(() => {
              const sourceLen = (result.cleaned_text ?? result.formatted_text ?? '').length
              return sourceLen > CHAT_WARN_CHARS ? (
                <p className="text-label-sm text-secondary">⚠ Text is very long ({Math.round(sourceLen / 1000)}K chars) — response quality may vary</p>
              ) : null
            })()}
            {chatHistory.length === 0 && (
              <p className="text-label-sm text-secondary">Ask a follow-up question about the video</p>
            )}
            <div className="flex items-center gap-3 bg-white border-2 border-outline-variant rounded-full px-5 py-2 focus-within:border-primary/40 focus-within:ring-4 focus-within:ring-primary/5 transition-all shadow-sm">
              <textarea
                ref={chatInputRef}
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
                className="flex-1 bg-transparent border-none focus:ring-0 focus:outline-none text-body-md text-on-surface placeholder:text-secondary/60 resize-none"
              />
              <button
                onClick={sendChatMessage}
                disabled={isChatting || !chatInput.trim()}
                title="Send"
                className="w-10 h-10 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center hover:scale-105 active:scale-95 transition-transform disabled:opacity-50 flex-shrink-0"
              >
                {isChatting
                  ? <span className="material-symbols-outlined text-[18px] pulse-dot">autorenew</span>
                  : <span className="material-symbols-outlined text-[18px]">send</span>
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
