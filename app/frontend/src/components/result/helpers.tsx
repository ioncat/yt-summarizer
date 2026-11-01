import type { Dispatch, SetStateAction } from 'react'
import ReactMarkdown from 'react-markdown'

export type Setter<T> = Dispatch<SetStateAction<T>>
export type Tab = 'subtitles' | 'cleaned' | 'summary' | 'mindmap' | 'chat'
export type ChatMsg = { role: 'user' | 'assistant'; content: string }

export function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="formatted-text markdown-content">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  )
}

export function formatDuration(seconds: number | null): string {
  if (seconds === 0) return '0:00'
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function formatDate(iso: string): string {
  const d = new Date(iso.endsWith('Z') ? iso : iso.replace(' ', 'T') + 'Z')
  const dd  = String(d.getDate()).padStart(2, '0')
  const mm  = String(d.getMonth() + 1).padStart(2, '0')
  const yyyy = d.getFullYear()
  const hh  = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${dd}.${mm}.${yyyy}, ${hh}:${min}`
}

export function MetaDot() {
  return <span className="w-1 h-1 rounded-full bg-outline-variant flex-shrink-0" />
}

  export const selectCls = 'bg-surface-container-low border border-outline-variant rounded-lg px-4 py-2 text-label-md focus:ring-2 focus:ring-primary/20 outline-none appearance-none disabled:opacity-50'
  export const btnSecondary = 'flex items-center gap-2 px-5 py-2 bg-surface-container-lowest text-secondary border border-outline-variant rounded-lg text-label-md font-medium hover:bg-surface-container-low active:scale-[0.98] transition-all'
  export const btnDanger    = 'flex items-center gap-2 px-5 py-2 text-error border border-error/30 rounded-lg text-label-md font-medium hover:bg-error/5 active:scale-[0.98] transition-all'
  export const btnAi        = 'flex items-center gap-2 px-5 py-2 bg-primary-container text-on-primary-container rounded-lg text-label-md font-medium hover:opacity-90 active:scale-[0.98] transition-all shadow-sm'
