import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ComponentProps } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ActionsBar } from '../components/result/ActionsBar'
import * as api from '../api'
import type { ResultResponse } from '../api'

vi.mock('../api', () => ({
  cancelMindmap: vi.fn(),
  saveAppSettings: vi.fn(),
  stopReextract: vi.fn(),
}))

function bar(result: Partial<ResultResponse>, setResult = vi.fn(), isLocalFile = true) {
  const noop = vi.fn()
  const props = {
    activeTab: 'subtitles', result: { video_id: 'file-ab12cd34', ...result } as ResultResponse, videoId: 'file-ab12cd34', isLocalFile,
    sttModel: 'base', setSttModel: noop, sttModels: [], reextractLang: 'auto', setReextractLang: noop, handleReextract: noop,
    cleanupModel: '', handleCleanupModelChange: noop, models: [], handleCancelCleanup: noop, handleCleanup: noop, summaryModel: '',
    handleSummaryModelChange: noop, handleCancelSummary: noop, handleSummarize: noop, stopMindmapPolling: noop, setResult,
    handleMindmap: noop, chatModel: '', handleChatModelChange: noop, chatHistory: [], copyChat: noop, chatCopied: false,
    handleClearChat: noop, displayText: 'text', handleCopy: noop, copied: false, handleDownload: noop, isDownloading: false,
    downloadFormat: 'mp4', setDownloadFormat: noop, downloadQuality: 'best', setDownloadQuality: noop, handleDelete: noop,
  }
  return { setResult, ...render(<ActionsBar {...(props as unknown as ComponentProps<typeof ActionsBar>)} />) }
}

describe('Stop on a re-extract (NS-11 stage 6)', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('a running re-transcription has a Stop button that stops it and frees the page at once', async () => {
    vi.mocked(api.stopReextract).mockResolvedValue(undefined)
    const { setResult } = bar({ reextract_in_progress: true, retranscribe_progress: 'segment 3 · 40%' })
    expect(screen.getByText('Re-transcribing…')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(api.stopReextract).toHaveBeenCalledWith('file-ab12cd34'))
    await waitFor(() => expect(setResult).toHaveBeenCalled())
    const update = setResult.mock.calls[0][0] as (r: ResultResponse) => ResultResponse
    expect(update({ video_id: 'x', reextract_in_progress: true } as ResultResponse).reextract_in_progress).toBe(false)
  })

  it('a YouTube re-extract has the Stop button too; nothing running means no Stop', () => {
    bar({ reextract_in_progress: true }, vi.fn(), false)
    expect(screen.getByText('Re-extracting…')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Stop' })).toBeTruthy()
  })

  it('no Stop button while nothing is being re-extracted', () => {
    bar({ reextract_in_progress: false })
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
  })

  it('a failing stop request is logged and the page is still freed (the next poll shows the truth)', async () => {
    vi.mocked(api.stopReextract).mockRejectedValue(new Error('boom'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { setResult } = bar({ reextract_in_progress: true })
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(setResult).toHaveBeenCalled())
  })
})
