import { ResultResponse } from '../../api'
import { Setter, Tab, ChatMsg } from './helpers'

interface TabsBarProps {
  result: ResultResponse
  activeTab: Tab
  setActiveTab: Setter<Tab>
  chatHistory: ChatMsg[]
}

export function TabsBar({ result, activeTab, setActiveTab, chatHistory }: TabsBarProps) {
  return (
            <div className="-mx-6 px-6 border-b border-outline-variant">
              <div className="flex items-end gap-8">
                {(['mindmap', 'subtitles', 'cleaned', 'summary'] as Tab[]).map(tab => {
                  const isActive = activeTab === tab
                  const isProcessing =
                    (tab === 'cleaned'  && result.cleanup_status === 'processing') ||
                    (tab === 'summary'  && result.summary_status === 'processing') ||
                    (tab === 'mindmap'  && result.mindmap_status === 'processing')
                  const label =
                    tab === 'mindmap'   ? 'Mind Map'  :
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
              </div>
            </div>
  )
}
