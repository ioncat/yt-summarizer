import { lazy, Suspense, RefObject } from 'react'
import ReactMarkdown from 'react-markdown'
import { ResultResponse } from '../../api'
import { renderText } from '../../utils/renderText'
import { Tab, ChatMsg, MarkdownContent } from './helpers'

const MindmapView = lazy(() => import('../MindmapView'))

interface TabContentProps {
  result: ResultResponse
  activeTab: Tab
  markdownEnabled: boolean
  setMarkdownEnabled: (v: boolean) => void
  chatBarVisible: boolean
  mindmapError: string
  handleMindmap: (force?: boolean) => void
  chatHistory: ChatMsg[]
  isChatting: boolean
  deleteChatMessage: (index: number) => void
  chatEndRef: RefObject<HTMLDivElement>
  displayText: string | null | undefined
}

export function TabContent({ result, activeTab, markdownEnabled, setMarkdownEnabled, chatBarVisible, mindmapError, handleMindmap, chatHistory, isChatting, deleteChatMessage, chatEndRef, displayText }: TabContentProps) {
  return (
          <div className="px-6 pb-8">

            {/* MD toggle pill — shown inside content for summary and cleaned tabs */}
            {(activeTab === 'summary' || activeTab === 'cleaned') && (
              <div className="flex justify-end mb-2">
                <button
                  onClick={() => { const next = !markdownEnabled; setMarkdownEnabled(next); localStorage.setItem('yt-md-enabled', String(next)) }}
                  title={markdownEnabled ? 'Markdown ON — click for plain text' : 'Enable Markdown rendering'}
                  className={`px-2 py-0.5 rounded border text-[10px] font-bold tracking-wider transition-colors ${markdownEnabled ? 'bg-primary text-on-primary border-primary' : 'border-outline-variant text-secondary hover:bg-surface-container-high'}`}
                >MD</button>
              </div>
            )}

            {activeTab === 'summary' ? (
              !result.summary_text ? (
                <div className="py-12 text-center text-secondary text-body-md">
                  {result.summary_status === 'processing' ? 'Summarization is running…'
                    : result.summary_status === 'failed' ? 'Summary failed. Click "Re-run summary" to try again.'
                    : 'No summary yet. Click "Summarize" above to generate one.'}
                </div>
              ) : (
                <>
                  {markdownEnabled ? <MarkdownContent text={result.summary_text!} /> : <div className="formatted-text">{renderText(result.summary_text!)}</div>}
                  {chatBarVisible && <div className="h-20" />}
                </>
              )
            ) : activeTab === 'mindmap' ? (
              result.mindmap_status === 'processing' ? (
                <div className="py-12 flex items-center justify-center gap-3 text-secondary text-body-md">
                  <span className="material-symbols-outlined pulse-dot">account_tree</span>
                  Generating mind map…
                </div>
              ) : result.mindmap_status === 'failed' || mindmapError ? (
                <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3 text-on-error-container text-body-sm">
                  {mindmapError || 'Mind map generation failed. Check Ollama and model settings.'}
                </div>
              ) : result.mindmap_text ? (
                <Suspense fallback={<div className="py-8 text-center text-secondary text-body-md">Loading…</div>}>
                  <MindmapView text={result.mindmap_text} title={result.title ?? undefined} onRegenerate={() => handleMindmap(true)} />
                </Suspense>
              ) : (
                <div className="py-16 text-center text-secondary text-body-md">
                  <span className="material-symbols-outlined text-[48px] block mb-4 text-outline-variant">account_tree</span>
                  No mind map yet. Click "Generate mind map" above to create one.
                </div>
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
                          ? (msg.role === 'assistant'
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
  )
}
