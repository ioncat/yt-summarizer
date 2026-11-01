import { ResultResponse } from '../../api'
import { Tab, MetaDot, formatDuration, formatDate } from './helpers'

interface MetaRibbonsProps {
  result: ResultResponse
  activeTab: Tab
  cleanupElapsedSeconds: number | null
  summaryElapsedSeconds: number | null
  cleanupDuration: number | null | undefined
  summaryDuration: number | null | undefined
}

export function MetaRibbons({ result, activeTab, cleanupElapsedSeconds, summaryElapsedSeconds, cleanupDuration, summaryDuration }: MetaRibbonsProps) {
  return (
<>
          {/* ── Meta ribbon: Subtitles tab stage info ── */}
          {activeTab === 'subtitles' && (result.subtitle_source === 'transcript' || result.subtitles_type) && (
            <div className="px-6 py-3 bg-surface-container-low border-b border-outline-variant flex flex-wrap items-center gap-x-3 gap-y-1 text-label-sm text-secondary">
              {result.subtitle_source === 'transcript' ? (
                <>
                  <span className="material-symbols-outlined text-[16px]">mic</span>
                  {result.transcription_duration_seconds != null
                    ? <span>Transcribed in {formatDuration(result.transcription_duration_seconds)}</span>
                    : <span>Whisper transcript</span>
                  }
                  {result.transcription_model && (
                    <><span className="meta-sep">·</span><span className="font-medium text-on-surface-variant">{result.transcription_model}</span></>
                  )}
                  {result.transcription_device && (
                    <><span className="meta-sep">·</span>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${result.transcription_device === 'cuda' ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300' : 'bg-surface-container text-secondary'}`}>
                      {result.transcription_device.toUpperCase()}
                    </span></>
                  )}
                  {result.transcription_finished_at && (
                    <><span className="meta-sep">·</span><span title="Transcription completed">{formatDate(result.transcription_finished_at)}</span></>
                  )}
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-[16px]">closed_caption</span>
                  <span>{result.subtitles_type === 'automatic_captions' ? 'Auto-captions' : result.subtitles_type === 'subtitles' ? 'Manual subtitles' : result.subtitles_type}</span>
                  <span className="meta-sep">·</span><span title="Extracted">{formatDate(result.created_at)}</span>
                </>
              )}
            </div>
          )}

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
</>
  )
}
