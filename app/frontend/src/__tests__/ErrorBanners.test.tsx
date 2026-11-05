import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ErrorBanners } from '../components/result/ErrorBanners'
import type { ResultResponse, StageRun } from '../api'

const run = (over: Partial<StageRun> = {}): StageRun => ({
  attempt: 2, status: 'failed', queue_item_id: 1, model: null, started_at: null, finished_at: '2026-11-05T10:00:00',
  error_code: 'no_speech', error_text: 'No speech was found in the file', meta: {}, progress_done: null, progress_total: null,
  runs: 2, last_done: null, ...over,
})

function renderBanners(stages: ResultResponse['stages'], activeTab: 'subtitles' | 'cleaned' = 'subtitles') {
  const noop = () => {}
  return render(
    <ErrorBanners result={{ video_id: 'v', stages } as ResultResponse} activeTab={activeTab} downloadError="" setDownloadError={noop}
      reextractError="" setReextractError={noop} cleanupError="" summaryError="" mindmapError="" />
  )
}

describe('ErrorBanners: a failed re-extract (NS-11 stage 6)', () => {
  it('says why the last re-extract failed and that the earlier subtitles are kept', () => {
    renderBanners({ transcribe: run() })
    expect(screen.getByText(/The last re-extract failed: No speech was found in the file/)).toBeTruthy()
    expect(screen.getByText(/The earlier subtitles, and everything made from them, are kept/)).toBeTruthy()
  })

  it('works for a YouTube re-extract too, and shows the raw message', () => {
    renderBanners({ extract: run({ error_code: 'no_subtitles', error_text: 'This video has no subtitles available.' }) })
    expect(screen.getByText(/This video has no subtitles available\./)).toBeTruthy()
  })

  it('shows nothing when the steps worked, were stopped, or are still running', () => {
    for (const status of ['done', 'cancelled', 'processing'] as const) {
      const { container, unmount } = renderBanners({ transcribe: run({ status }) })
      expect(container.textContent).toBe('')
      unmount()
    }
  })

  it('shows nothing on other tabs', () => {
    const { container } = renderBanners({ transcribe: run() }, 'cleaned')
    expect(container.textContent).toBe('')
  })
})
