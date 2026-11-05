import { MutableRefObject } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import {
  deleteResult, startCleanup, cancelCleanup, startSummary, cancelSummary,
  startMindmap, reextractSubtitles, saveSettings, queueBulkAdd, downloadVideo,
  ResultResponse,
} from '../../api'
import { Setter } from './helpers'

type Interval = MutableRefObject<ReturnType<typeof setInterval> | null>
type Prompts = MutableRefObject<{ system_prompt: string | null; user_prompt_template: string | null }>

interface UseResultHandlersParams {
  videoId: string | undefined
  result: ResultResponse | null
  navigate: NavigateFunction
  displayText: string | null | undefined
  setCopied: Setter<boolean>
  stopPolling: () => void
  stopCleanupTimer: () => void
  stopSummaryPolling: () => void
  stopSummaryTimer: () => void
  stopMindmapPolling: () => void
  setCleanupElapsedSeconds: Setter<number | null>
  cleanupElapsedRef: MutableRefObject<number | null>
  setLocalCleanupDuration: Setter<number | null>
  setSummaryElapsedSeconds: Setter<number | null>
  summaryElapsedRef: MutableRefObject<number | null>
  setLocalSummaryDuration: Setter<number | null>
  setResult: Setter<ResultResponse | null>
  setDownloadError: Setter<string>
  setIsDownloading: Setter<boolean>
  downloadFormat: 'mp4' | 'mp3'
  downloadQuality: string
  isLocalFile: boolean | undefined
  reextractLang: string
  sttModel: string
  setReextractError: Setter<string>
  loadResult: (switchTab?: boolean) => void
  setCleanupModel: Setter<string>
  cleanupPromptsRef: Prompts
  setSummaryModel: Setter<string>
  summaryPromptsRef: Prompts
  setChatModel: Setter<string>
  requestNotifyPermission: () => void
  setCleanupError: Setter<string>
  setSummaryError: Setter<string>
  setMindmapError: Setter<string>
  setQueuedMsg: Setter<string | null>
  pollRef: Interval
  summaryPollRef: Interval
  mindmapPollRef: Interval
  autoSummarizeAfterCleanupRef: MutableRefObject<boolean>
}

export function useResultHandlers({
  videoId, result, navigate, displayText, setCopied,
  stopPolling, stopCleanupTimer, stopSummaryPolling, stopSummaryTimer, stopMindmapPolling,
  setCleanupElapsedSeconds, cleanupElapsedRef, setLocalCleanupDuration,
  setSummaryElapsedSeconds, summaryElapsedRef, setLocalSummaryDuration,
  setResult, setDownloadError, setIsDownloading, downloadFormat, downloadQuality,
  isLocalFile, reextractLang, sttModel, setReextractError, loadResult,
  setCleanupModel, cleanupPromptsRef, setSummaryModel, summaryPromptsRef, setChatModel,
  requestNotifyPermission, setCleanupError, setSummaryError, setMindmapError, setQueuedMsg,
  pollRef, summaryPollRef, mindmapPollRef, autoSummarizeAfterCleanupRef,
}: UseResultHandlersParams) {
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

  async function handleDownload() {
    if (!videoId) return
    setDownloadError('')
    setIsDownloading(true)
    try {
      await downloadVideo(videoId, downloadFormat, downloadQuality)
    } catch (err: any) {
      setDownloadError(err.message ?? 'Download failed')
    } finally {
      setIsDownloading(false)
    }
  }


  async function handleReextract() {
    if (!videoId) return
    const ok = window.confirm(
      isLocalFile
        ? 'Re-transcribe this file with Whisper?\n\n' +
          'This will:\n' +
          '• Replace the current Subtitles tab content with a fresh transcription\n' +
          '• Clear the Cleaned tab (you will need to re-run AI Cleanup)\n' +
          '• Clear the Summary tab (you will need to re-run summarization)\n\n' +
          'Note: the original file must still be present in the uploads folder.\n\nContinue?'
        : 'Re-extract subtitles from YouTube?\n\n' +
          'This will:\n' +
          '• Replace the current Subtitles tab content with a fresh download\n' +
          '• Clear the Cleaned tab (you will need to re-run AI Cleanup)\n' +
          '• Clear the Summary tab (you will need to re-run summarization)\n\n' +
          'Continue?'
    )
    if (!ok) return
    setReextractError('')
    try {
      await reextractSubtitles(videoId, reextractLang, isLocalFile ? sttModel : undefined)
      setResult(prev => prev ? { ...prev, reextract_in_progress: true } : prev)
      loadResult()
    } catch (err: any) {
      console.error('[Result] reextract failed:', err)
      setReextractError(err.message ?? (isLocalFile ? 'Failed to re-transcribe. The original file may have been deleted.' : 'Failed to re-extract subtitles'))
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

  async function handleChatModelChange(newModel: string) {
    setChatModel(newModel)
    try {
      await saveSettings('chat', { system_prompt: null, user_prompt_template: null, model: newModel || null })
    } catch (err) { console.error('[Result] saveSettings chat model failed:', err) }
  }

  async function handleCleanup() {
    if (!videoId || !result) return
    requestNotifyPermission()
    try {
      setCleanupError('')
      if (result.url?.startsWith('local://')) {
        await startCleanup(videoId)
      } else {
        await queueBulkAdd([result.url], ['cleanup'], true)
      }
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
        if (result.url?.startsWith('local://')) {
          await startCleanup(videoId)
          autoSummarizeAfterCleanupRef.current = true
        } else {
          await queueBulkAdd([result.url], ['cleanup', 'summary'], true)
        }
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
      if (result.url?.startsWith('local://')) {
        await startSummary(videoId)
      } else {
        await queueBulkAdd([result.url], ['summary'], true)
      }
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
      // One path for every video, local files too: the endpoint queues the work (NS-11 stage 2), sets the status at once
      // and hands back the saved map when there is one and this is not a Regenerate.
      const res = await startMindmap(videoId, force)
      if (res?.status === 'done' && res.mindmap_text) {
        setResult(r => r ? { ...r, mindmap_text: res.mindmap_text!, mindmap_status: 'done' } : r)
        return
      }
      // queued: show "generating" but KEEP the saved map in state until the new one arrives (a refused request or a
      // failed run must not leave the page without it)
      setResult(r => r ? { ...r, mindmap_status: 'processing' } : r)
      setQueuedMsg('mindmap')
      stopMindmapPolling()
      mindmapPollRef.current = setInterval(() => loadResult(false), 3000)
    } catch (err: unknown) {
      console.error('[Mindmap] failed:', err)
      setMindmapError(err instanceof Error ? err.message : 'Unknown error')
    }
  }

  return {
    handleCopy, handleCancelCleanup, handleCancelSummary, handleDelete, handleDownload,
    handleReextract, handleCleanupModelChange, handleSummaryModelChange, handleChatModelChange,
    handleCleanup, handleSummarize, handleMindmap,
  }
}
