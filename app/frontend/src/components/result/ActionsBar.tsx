import { cancelMindmap, saveAppSettings, ResultResponse, SttModelInfo } from '../../api'
import { Setter, Tab, ChatMsg, selectCls, btnSecondary, btnDanger, btnAi } from './helpers'

interface ActionsBarProps {
  activeTab: Tab
  result: ResultResponse
  videoId: string | undefined
  isLocalFile: boolean | undefined
  sttModel: string
  setSttModel: Setter<string>
  sttModels: SttModelInfo[]
  reextractLang: string
  setReextractLang: Setter<string>
  handleReextract: () => void
  cleanupModel: string
  handleCleanupModelChange: (m: string) => void
  models: string[]
  handleCancelCleanup: () => void
  handleCleanup: () => void
  summaryModel: string
  handleSummaryModelChange: (m: string) => void
  handleCancelSummary: () => void
  handleSummarize: () => void
  stopMindmapPolling: () => void
  setResult: Setter<ResultResponse | null>
  handleMindmap: (force?: boolean) => void
  chatModel: string
  handleChatModelChange: (m: string) => void
  chatHistory: ChatMsg[]
  copyChat: () => void
  chatCopied: boolean
  handleClearChat: () => void
  displayText: string | null | undefined
  handleCopy: () => void
  copied: boolean
  handleDownload: () => void
  isDownloading: boolean
  downloadFormat: 'mp4' | 'mp3'
  setDownloadFormat: Setter<'mp4' | 'mp3'>
  downloadQuality: string
  setDownloadQuality: Setter<string>
  handleDelete: () => void
}

export function ActionsBar({ activeTab, result, videoId, isLocalFile, sttModel, setSttModel, sttModels, reextractLang, setReextractLang, handleReextract, cleanupModel, handleCleanupModelChange, models, handleCancelCleanup, handleCleanup, summaryModel, handleSummaryModelChange, handleCancelSummary, handleSummarize, stopMindmapPolling, setResult, handleMindmap, chatModel, handleChatModelChange, chatHistory, copyChat, chatCopied, handleClearChat, displayText, handleCopy, copied, handleDownload, isDownloading, downloadFormat, setDownloadFormat, downloadQuality, setDownloadQuality, handleDelete }: ActionsBarProps) {
  return (
            <div className="flex flex-wrap items-center gap-3">

              {/* Subtitles tab controls */}
              {activeTab === 'subtitles' && (
                <>
                  {/* STT model selector — only for local file transcriptions */}
                  {isLocalFile && (
                    <div className="relative min-w-[160px]">
                      <select
                        value={sttModel}
                        onChange={e => {
                          setSttModel(e.target.value)
                          saveAppSettings({ stt_model: e.target.value }).catch(() => {})
                        }}
                        className={`${selectCls} w-full pr-8`}
                        title="STT model for re-transcription"
                      >
                        <option value="">— STT model —</option>
                        {sttModels.filter(m => m.downloaded).map(m => (
                          <option key={m.name} value={m.name}>{m.name}</option>
                        ))}
                      </select>
                      <span className="material-symbols-outlined absolute right-2 top-2.5 text-secondary pointer-events-none text-[16px]">expand_more</span>
                    </div>
                  )}
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
                    title={isLocalFile ? 'Re-run Whisper transcription. Cleanup and Summary will be cleared.' : 'Re-fetch subtitles from YouTube. Cleanup and Summary will be cleared.'}
                  >
                    <span className="material-symbols-outlined text-[18px]">refresh</span>
                    {result.reextract_in_progress ? (isLocalFile ? 'Re-transcribing…' : 'Re-extracting…') : (isLocalFile ? 'Re-transcribe' : 'Re-extract')}
                  </button>
                  {result.reextract_in_progress && isLocalFile && result.retranscribe_progress && (
                    <span className="text-label-sm text-secondary animate-pulse">{result.retranscribe_progress}</span>
                  )}
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

              {/* Mindmap tab controls */}
              {activeTab === 'mindmap' && (
                result.mindmap_status === 'processing' ? (
                  <button onClick={async () => { await cancelMindmap(videoId!); stopMindmapPolling(); setResult(r => r ? { ...r, mindmap_status: null } : r) }} className={btnSecondary}>
                    <span className="material-symbols-outlined text-[18px]">stop_circle</span>Stop
                  </button>
                ) : (
                  <button onClick={() => handleMindmap(!!result.mindmap_text)} className={btnAi}>
                    <span className="material-symbols-outlined text-[18px]">account_tree</span>
                    {result.mindmap_text ? 'Regenerate mind map' : 'Generate mind map'}
                  </button>
                )
              )}

              {/* Chat tab controls */}
              {activeTab === 'chat' && (
                <div className="relative min-w-[180px]">
                  <select
                    value={chatModel || summaryModel}
                    onChange={e => handleChatModelChange(e.target.value)}
                    disabled={models.length === 0}
                    title={models.length === 0 ? 'Ollama offline' : 'Model for chat'}
                    className={`${selectCls} w-full pr-8`}
                  >
                    <option value="">— chat model —</option>
                    {models.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                  <span className="material-symbols-outlined absolute right-2 top-2.5 text-secondary pointer-events-none text-[16px]">expand_more</span>
                </div>
              )}

              {/* Benchmark — not applicable for local file transcriptions */}
              {activeTab !== 'chat' && !isLocalFile && (
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

              {/* Open video — not applicable for local file transcriptions */}
              {!isLocalFile && (
                <a href={result.url} target="_blank" rel="noreferrer" className={btnSecondary}>
                  <span className="material-symbols-outlined text-[18px]">open_in_new</span>Open video
                </a>
              )}

              {/* Download — not applicable for local file transcriptions */}
              {!isLocalFile && (
                <div className="flex items-center gap-1">
                  <button
                    onClick={handleDownload}
                    disabled={isDownloading}
                    className={btnSecondary + ' disabled:opacity-50'}
                  >
                    <span className="material-symbols-outlined text-[18px]">
                      {isDownloading ? 'hourglass_top' : 'download'}
                    </span>
                    {isDownloading ? 'Downloading…' : 'Download'}
                  </button>
                  <select
                    value={downloadFormat}
                    onChange={e => setDownloadFormat(e.target.value as 'mp4' | 'mp3')}
                    className="h-9 px-2 text-[11px] bg-surface-container-low border border-outline-variant rounded-lg text-on-surface focus:outline-none focus:border-primary"
                    title="Format"
                  >
                    <option value="mp4">MP4</option>
                    <option value="mp3">MP3</option>
                  </select>
                  <select
                    value={downloadQuality}
                    onChange={e => setDownloadQuality(e.target.value)}
                    className="h-9 px-2 text-[11px] bg-surface-container-low border border-outline-variant rounded-lg text-on-surface focus:outline-none focus:border-primary"
                    title="Quality"
                  >
                    <option value="best">Best</option>
                    <option value="1080p">1080p</option>
                    <option value="720p">720p</option>
                    <option value="480p">480p</option>
                  </select>
                </div>
              )}

              {/* Delete */}
              <button onClick={handleDelete} className={btnDanger}>
                <span className="material-symbols-outlined text-[18px]">delete</span>Delete
              </button>
            </div>
  )
}
