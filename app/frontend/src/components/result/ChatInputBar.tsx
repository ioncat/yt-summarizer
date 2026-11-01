import { RefObject } from 'react'
import { ResultResponse } from '../../api'
import { ChatMsg } from './helpers'

const CHAT_WARN_CHARS = 100_000

interface ChatInputBarProps {
  result: ResultResponse
  chatHistory: ChatMsg[]
  chatInput: string
  setChatInput: (v: string) => void
  isChatting: boolean
  chatInputRef: RefObject<HTMLTextAreaElement>
  sendChatMessage: () => void
}

export function ChatInputBar({ result, chatHistory, chatInput, setChatInput, isChatting, chatInputRef, sendChatMessage }: ChatInputBarProps) {
  return (
        <div className="fixed bottom-6 left-0 md:left-64 right-0 z-30 px-6 md:px-8 pointer-events-none">
          <div className="max-w-[1200px] mx-auto flex justify-center pointer-events-none">
          <div className="w-full max-w-2xl pointer-events-auto">
          <div className="bg-surface/95 dark:bg-surface-container-low/95 backdrop-blur-md border border-outline-variant rounded-2xl shadow-2xl px-5 py-4 space-y-2">
            {(() => {
              const sourceLen = (result.cleaned_text ?? result.formatted_text ?? '').length
              return sourceLen > CHAT_WARN_CHARS ? (
                <p className="text-label-sm text-secondary">⚠ Text is very long ({Math.round(sourceLen / 1000)}K chars) — response quality may vary</p>
              ) : null
            })()}
            {chatHistory.length === 0 && (
              <p className="text-label-sm text-secondary">Ask a follow-up question about the video</p>
            )}
            <div className="flex items-center gap-3 bg-surface-container-low border border-outline-variant rounded-xl px-4 py-2 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10 transition-all">
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
          </div>
        </div>
  )
}
