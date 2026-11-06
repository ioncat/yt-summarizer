/** Where a speech-to-text result came from: a local audio / video file or YouTube. Shown in History and on the result page. */
interface SourceItem {
  url?: string | null
  subtitle_source?: string | null
}

const AUDIO_EXTS = new Set(['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.opus', '.wma'])

function getSourceType(item: SourceItem): 'youtube' | 'local_audio' | 'local_video' {
  if (!item.url?.startsWith('local://')) return 'youtube'
  const filename = item.url.replace('local://', '')
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase()
  return AUDIO_EXTS.has(ext) ? 'local_audio' : 'local_video'
}

export function SourceBadge({ item }: { item: SourceItem }) {
  if (item.subtitle_source !== 'transcript') return null
  const src = getSourceType(item)
  const configs = {
    local_audio: { icon: 'audio_file',   title: 'Local audio file (STT)' },
    local_video: { icon: 'movie',        title: 'Local video file (STT)' },
    youtube:     { icon: 'smart_display', title: 'YouTube (STT)' },
  }
  const c = configs[src]
  return (
    <span
      title={c.title}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-secondary-container text-on-secondary-container text-tag-uppercase font-bold tracking-wider uppercase"
    >
      <span className="material-symbols-outlined text-[14px]">{c.icon}</span>
      STT
    </span>
  )
}
