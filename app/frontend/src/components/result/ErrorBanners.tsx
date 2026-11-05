import { ResultResponse } from '../../api'
import { Setter, Tab } from './helpers'

interface ErrorBannersProps {
  result: ResultResponse
  activeTab: Tab
  downloadError: string
  setDownloadError: Setter<string>
  reextractError: string
  setReextractError: Setter<string>
  cleanupError: string
  summaryError: string
  mindmapError: string
}

export function ErrorBanners({ result, activeTab, downloadError, setDownloadError, reextractError, setReextractError, cleanupError, summaryError, mindmapError }: ErrorBannersProps) {
  // A video that is in History had its extraction / transcription done, so a FAILED run of that step on it is a failed re-extract
  // or re-transcribe (NS-11 stage 6): say why and that nothing was replaced.
  const failedRun = [result.stages?.transcribe, result.stages?.extract].find(r => r?.status === 'failed')
  return (
<>
            {activeTab === 'subtitles' && failedRun && (
              <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3 flex items-start gap-3">
                <span className="material-symbols-outlined text-error text-[18px] mt-0.5 shrink-0">error</span>
                <p className="text-body-sm text-on-error-container">
                  The last re-extract failed: {failedRun.error_text || 'no reason was recorded'}. The earlier subtitles, and everything made from them, are kept.
                </p>
              </div>
            )}
            {downloadError && (
              <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3 flex items-start gap-3">
                <span className="material-symbols-outlined text-error text-[18px] mt-0.5 shrink-0">error</span>
                <div>
                  <p className="text-body-sm text-on-error-container">{downloadError}</p>
                  <button
                    onClick={() => setDownloadError('')}
                    className="mt-1 text-label-sm text-on-error-container/70 hover:text-on-error-container underline"
                  >Dismiss</button>
                </div>
              </div>
            )}
            {reextractError && (
              <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3 flex items-start gap-3">
                <span className="material-symbols-outlined text-error text-[18px] mt-0.5 shrink-0">error</span>
                <div>
                  <p className="text-body-sm text-on-error-container">{reextractError}</p>
                  <button
                    onClick={() => setReextractError('')}
                    className="mt-1 text-label-sm text-on-error-container/70 hover:text-on-error-container underline"
                  >Dismiss</button>
                </div>
              </div>
            )}
            {activeTab === 'cleaned' && (result.cleanup_status === 'failed' || cleanupError) && (
              <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3">
                <p className="text-body-sm text-on-error-container">
                  {cleanupError || result.cleanup_error || 'Cleanup failed. Possible causes: Ollama not running, no model selected, or model timed out on large paragraphs. Check backend log.'}
                </p>
              </div>
            )}
            {activeTab === 'summary' && (result.summary_status === 'failed' || summaryError) && (
              <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3">
                <p className="text-body-sm text-on-error-container">
                  {summaryError || result.summary_error || 'Summarization failed. Possible causes: Ollama not running, no model selected, or a stage timed out. For very long texts try a stronger model or wait for hierarchical map-reduce.'}
                </p>
              </div>
            )}
            {activeTab === 'mindmap' && (result.mindmap_status === 'failed' || mindmapError) && (
              <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3">
                <p className="text-body-sm text-on-error-container">
                  {mindmapError || result.mindmap_error || 'Mind map generation failed. Check Ollama and model settings.'}
                </p>
              </div>
            )}
</>
  )
}
