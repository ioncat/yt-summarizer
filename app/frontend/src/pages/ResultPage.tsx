import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  getResult,
  getSettings, getModels,
  getSttModels,
  ResultResponse, SttModelInfo,
} from '../api'
import { Tab } from '../components/result/helpers'
import { ResultHeader } from '../components/result/ResultHeader'
import { MetaRibbons } from '../components/result/MetaRibbons'
import { ActionsBar } from '../components/result/ActionsBar'
import { ErrorBanners } from '../components/result/ErrorBanners'
import { JobsBanner } from '../components/result/JobsBanner'
import { CleanupFirstPrompt } from '../components/result/CleanupFirstPrompt'
import { queuedLineVisible, queuedStagesRunning, QueuedMsg } from '../components/result/queuedMessage'
import { TabsBar } from '../components/result/TabsBar'
import { TabContent } from '../components/result/TabContent'
import { StageTable } from '../components/result/StageTable'
import { ChatInputBar } from '../components/result/ChatInputBar'
import { useResultChat } from '../components/result/useResultChat'
import { useResultHandlers } from '../components/result/useResultHandlers'

export default function ResultPage() {
  const { videoId } = useParams<{ videoId: string }>()
  const navigate = useNavigate()
  const [result, setResult]             = useState<ResultResponse | null>(null)
  const [error, setError]               = useState('')
  const [cleanupError, setCleanupError]   = useState('')
  const [summaryError, setSummaryError]   = useState('')
  const [reextractError, setReextractError] = useState('')
  const [copied, setCopied]             = useState(false)
  const [activeTab, setActiveTab]       = useState<Tab>('subtitles')
  const [markdownEnabled, setMarkdownEnabled] = useState(() =>
    localStorage.getItem('yt-md-enabled') === 'true'
  )
  const [mindmapError, setMindmapError]     = useState('')
  const mindmapPollRef          = useRef<ReturnType<typeof setInterval> | null>(null)
  const prevMindmapStatusRef    = useRef<string | null | undefined>(undefined)
  const initialTabSetRef        = useRef(false)
  const [reextractLang, setReextractLang] = useState('auto')
  const [sttModel, setSttModel]           = useState('')
  const [sttModels, setSttModels]         = useState<SttModelInfo[]>([])
  const [cleanupModel, setCleanupModel]   = useState('')
  const [summaryModel, setSummaryModel]   = useState('')
  const [chatModel, setChatModel]         = useState('')
  const [models, setModels]               = useState<string[]>([])
  const [cleanupElapsedSeconds, setCleanupElapsedSeconds] = useState<number | null>(null)
  const [summaryElapsedSeconds, setSummaryElapsedSeconds] = useState<number | null>(null)
  const [localCleanupDuration, setLocalCleanupDuration]   = useState<number | null>(null)
  const [localSummaryDuration, setLocalSummaryDuration]   = useState<number | null>(null)

  // Download
  const [downloadFormat, setDownloadFormat] = useState<'mp4' | 'mp3'>('mp4')
  const [downloadQuality, setDownloadQuality] = useState('best')
  const [isDownloading, setIsDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')

  const [ollamaUrl, setOllamaUrl]   = useState('')
  const [queuedMsg, setQueuedMsg] = useState<string | null>(null)
  const [askCleanupFirst, setAskCleanupFirst] = useState(false)    // Summarize pressed before any cleanup: ask in the page

  const {
    chatHistory, setChatHistory, chatInput, setChatInput, isChatting, chatCopied,
    chatEndRef, chatInputRef, chatHistoryLoadedRef,
    sendChatMessage, deleteChatMessage, handleClearChat, copyChat,
  } = useResultChat({ videoId, result, chatModel, summaryModel, ollamaUrl, setActiveTab })

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
        const isFirstLoad = prevMindmapStatusRef.current === undefined
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

        if (isFirstLoad && data.language) {
          setReextractLang(data.language)
        }

        if (isFirstLoad && !initialTabSetRef.current) {
          initialTabSetRef.current = true
          if (data.mindmap_text) setActiveTab('mindmap')
          else if (data.summary_text) setActiveTab('summary')
          else setActiveTab('subtitles')
        } else if (switchTab && !initialTabSetRef.current) {
          initialTabSetRef.current = true
          if (data.summary_status === 'done') setActiveTab('summary')
          else if (data.cleanup_status === 'done') setActiveTab('cleaned')
          else setActiveTab('subtitles')
        } else {
          if (prevCleanup === 'processing' && data.cleanup_status === 'done') {
            notify('AI Cleanup complete', data.title ?? undefined)
            setActiveTab('cleaned')
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
      .catch(err => {
        console.error('[Result] getResult failed:', err)
        setError(err instanceof Error && err.message === 'Result not found'
          ? `Video "${videoId}" was not found in History.` : 'Could not load result')
      })
  }

  useEffect(() => {
    initialTabSetRef.current = false
    loadResult(true)
    return () => { initialTabSetRef.current = false; stopPolling(); stopSummaryPolling(); stopMindmapPolling(); stopCleanupTimer(); stopSummaryTimer() }
  }, [videoId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!result?.reextract_in_progress) return
    const id = setInterval(() => loadResult(), 3000)
    return () => clearInterval(id)
  }, [result?.reextract_in_progress]) // eslint-disable-line react-hooks/exhaustive-deps

  function loadSettings() {
    Promise.all([getSettings(), getModels(), getSttModels()])
      .then(([s, list, sttList]) => {
        setCleanupModel(s.cleanup.model ?? '')
        setSummaryModel(s.summarization.model ?? '')
        setChatModel(s.chat?.model ?? '')
        setOllamaUrl(s.app.ollama_url ?? '')
        setModels(list)
        setSttModel(s.app.stt_model ?? '')
        setSttModels(sttList)
        setDownloadFormat((s.app.download_default_format as 'mp4' | 'mp3') ?? 'mp4')
        setDownloadQuality(s.app.download_default_quality ?? 'best')
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

  // The "Added to queue" line goes away for good when the queued work is over (NS-17 item 2)
  useEffect(() => {
    if (queuedMsg && result && !queuedStagesRunning(queuedMsg as QueuedMsg, result)) setQueuedMsg(null)
  }, [queuedMsg, result]) // eslint-disable-line react-hooks/exhaustive-deps

  const displayText =
    activeTab === 'summary' ? result?.summary_text :
    activeTab === 'cleaned' ? (result?.cleaned_text ?? result?.formatted_text) :
    activeTab === 'chat'    ? null :
    result?.formatted_text

  const isLocalFile = result?.subtitle_source === 'transcript' && result?.video_id?.startsWith('file-')

  const {
    handleCopy, handleCancelCleanup, handleCancelSummary, handleStopAll, handleDelete, handleDownload,
    handleReextract, handleCleanupModelChange, handleSummaryModelChange, handleChatModelChange,
    handleCleanup, handleSummarize, handleCleanupThenSummarize, handleSummarizeAnyway, handleMindmap,
  } = useResultHandlers({
    videoId, result, navigate, displayText, setCopied,
    stopPolling, stopCleanupTimer, stopSummaryPolling, stopSummaryTimer, stopMindmapPolling,
    setCleanupElapsedSeconds, cleanupElapsedRef, setLocalCleanupDuration,
    setSummaryElapsedSeconds, summaryElapsedRef, setLocalSummaryDuration,
    setResult, setDownloadError, setIsDownloading, downloadFormat, downloadQuality,
    isLocalFile, reextractLang, sttModel, setReextractError, loadResult,
    setCleanupModel, cleanupPromptsRef, setSummaryModel, summaryPromptsRef, setChatModel,
    requestNotifyPermission, setCleanupError, setSummaryError, setMindmapError, setQueuedMsg, setAskCleanupFirst,
    pollRef, summaryPollRef, mindmapPollRef,
  })

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
    && result.summary_status === 'done' && !!result.summary_text && !!ollamaUrl && !!(chatModel || summaryModel)

  const subtitlesCount = result.char_count ?? result.formatted_text?.length ?? null
  const cleanedCount   = result.cleaned_text?.length ?? null
  const summaryCount   = result.summary_text?.length ?? null
  const displayCharCount =
    activeTab === 'summary' ? summaryCount :
    activeTab === 'cleaned' ? cleanedCount : subtitlesCount
  const charCountOf = activeTab === 'summary' ? 'summary' : activeTab === 'cleaned' ? 'cleaned text' : 'subtitles'


  return (
    <>
      <div className={`p-6 md:p-8 max-w-[1200px] mx-auto${chatBarVisible ? ' pb-36' : ''}`}>
        <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm overflow-hidden">

          {/* ── Card header: title + star ── */}
          <ResultHeader result={result} videoId={videoId} setResult={setResult} displayCharCount={displayCharCount} charCountOf={charCountOf} />

          <MetaRibbons
            result={result}
            activeTab={activeTab}
            cleanupElapsedSeconds={cleanupElapsedSeconds}
            summaryElapsedSeconds={summaryElapsedSeconds}
            cleanupDuration={cleanupDuration}
            summaryDuration={summaryDuration}
          />

          {/* ── Queue message ── */}
          {queuedLineVisible(queuedMsg, activeTab, result) && (
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
            <ActionsBar
              activeTab={activeTab} result={result} videoId={videoId} isLocalFile={isLocalFile}
              sttModel={sttModel} setSttModel={setSttModel} sttModels={sttModels}
              reextractLang={reextractLang} setReextractLang={setReextractLang} handleReextract={handleReextract}
              cleanupModel={cleanupModel} handleCleanupModelChange={handleCleanupModelChange} models={models}
              handleCancelCleanup={handleCancelCleanup} handleCleanup={handleCleanup}
              summaryModel={summaryModel} handleSummaryModelChange={handleSummaryModelChange}
              handleCancelSummary={handleCancelSummary} handleSummarize={handleSummarize}
              stopMindmapPolling={stopMindmapPolling} setResult={setResult} handleMindmap={handleMindmap}
              chatModel={chatModel} handleChatModelChange={handleChatModelChange}
              chatHistory={chatHistory} copyChat={copyChat} chatCopied={chatCopied} handleClearChat={handleClearChat}
              displayText={displayText} handleCopy={handleCopy} copied={copied}
              handleDownload={handleDownload} isDownloading={isDownloading}
              downloadFormat={downloadFormat} setDownloadFormat={setDownloadFormat}
              downloadQuality={downloadQuality} setDownloadQuality={setDownloadQuality}
              handleDelete={handleDelete}
            />

            {askCleanupFirst && activeTab === 'summary' && (
              <CleanupFirstPrompt result={result} onCleanupThenSummarize={handleCleanupThenSummarize}
                onSummarizeAnyway={handleSummarizeAnyway} onCancel={() => setAskCleanupFirst(false)} />
            )}

            {/* What is waiting or running for this video, with one Stop (NS-16) */}
            <JobsBanner result={result} handleStopAll={handleStopAll} />

            {/* Error banners */}
            <ErrorBanners
              result={result} activeTab={activeTab}
              downloadError={downloadError} setDownloadError={setDownloadError}
              reextractError={reextractError} setReextractError={setReextractError}
              cleanupError={cleanupError} summaryError={summaryError} mindmapError={mindmapError}
            />

            {/* Tabs bar */}
            <TabsBar result={result} activeTab={activeTab} setActiveTab={setActiveTab} chatHistory={chatHistory} />
          </div>

          {/* ── Tab content ── */}
          <TabContent
            result={result} activeTab={activeTab}
            markdownEnabled={markdownEnabled}
            setMarkdownEnabled={setMarkdownEnabled}
            chatBarVisible={chatBarVisible} mindmapError={mindmapError} handleMindmap={handleMindmap}
            chatHistory={chatHistory} isChatting={isChatting} deleteChatMessage={deleteChatMessage}
            chatEndRef={chatEndRef} displayText={displayText}
          />

          {/* ── What ran, with which model, and why a step failed (NS-25) ── */}
          <StageTable result={result} chosenDownload={{ format: downloadFormat, quality: downloadQuality }} />
        </div>
      </div>

      {/* ── Floating chat input bar ── */}
      {chatBarVisible && (
        <ChatInputBar
          result={result} chatHistory={chatHistory} chatInput={chatInput} setChatInput={setChatInput}
          isChatting={isChatting} chatInputRef={chatInputRef} sendChatMessage={sendChatMessage}
        />
      )}
    </>
  )
}
