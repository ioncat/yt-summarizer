import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StageTable } from '../components/result/StageTable'
import type { ResultResponse, StageRun } from '../api'

const run = (over: Partial<StageRun> = {}): StageRun => ({
  attempt: 1, status: 'done', queue_item_id: 3, model: 'qwen', started_at: '2026-11-01T10:00:00', finished_at: '2026-11-01T10:02:05',
  error_code: null, error_text: null, meta: {}, progress_done: null, progress_total: null, runs: 1, last_done: null, ...over,
})
const result = (stages: ResultResponse['stages']) => ({ video_id: 'v', stages } as ResultResponse)

describe('StageTable (NS-25)', () => {
  it('shows nothing for a video with no recorded runs', () => {
    const { container } = render(<StageTable result={result({})} />)
    expect(container.firstChild).toBeNull()
    expect(render(<StageTable result={{ video_id: 'v' } as ResultResponse} />).container.firstChild).toBeNull()
  })

  it('lists the steps that ran, with status, model and how long the saved result took', () => {
    render(<StageTable result={result({ cleanup: run({ model: 'gemma' }), summary: run({ model: 'qwen' }) })} />)
    expect(screen.getByText('Processing steps (2)')).toBeTruthy()
    expect(screen.getByText('Cleanup')).toBeTruthy()
    expect(screen.getByText('gemma')).toBeTruthy()
    expect(screen.getAllByText('done')).toHaveLength(2)
    expect(screen.getAllByText(/2:05/)).toHaveLength(2)
    expect(document.querySelector('details')!.open).toBe(false)     // all fine: collapsed
  })

  it('a failed step opens the table, says why in plain words, and shows the model of the earlier successful run', () => {
    const good = run({ model: 'model-good' })
    render(<StageTable result={result({
      summary: run({ status: 'failed', attempt: 2, runs: 2, model: 'model-bad', error_code: 'empty_answer',
        error_text: 'model returned nothing', last_done: good }),
    })} />)
    expect(document.querySelector('details')!.open).toBe(true)
    expect(screen.getByText('failed')).toBeTruthy()
    expect(screen.getByText('the model returned nothing')).toBeTruthy()
    expect(screen.getByText('model returned nothing')).toBeTruthy()
    expect(screen.getByText('model-good')).toBeTruthy()
    expect(screen.queryByText('model-bad')).toBeNull()
    expect(screen.getByText(/Showing the earlier successful run \(model-good\)/)).toBeTruthy()
    expect(screen.getByText('2 runs so far')).toBeTruthy()
  })

  it('a running or stopped step is named as such', () => {
    render(<StageTable result={result({
      cleanup: run({ status: 'processing', finished_at: null }),
      mindmap: run({ status: 'cancelled', finished_at: null }),
    })} />)
    expect(screen.getByText('running')).toBeTruthy()
    expect(screen.getByText('stopped')).toBeTruthy()
  })

  it('a running step shows its live counters with the unit word (stage 4b)', () => {
    render(<StageTable result={result({
      cleanup: run({ status: 'processing', finished_at: null, progress_done: 3, progress_total: 10, meta: { unit: 'paragraph' } }),
      summary: run({ status: 'processing', finished_at: null, progress_done: 1, progress_total: 4, meta: {} }),
    })} />)
    expect(screen.getByText('paragraph 3 / 10')).toBeTruthy()
    expect(screen.getByText('1 / 4')).toBeTruthy()
  })

  it('a finished or waiting step shows no counters', () => {
    render(<StageTable result={result({
      cleanup: run({ progress_done: 10, progress_total: 10, meta: { unit: 'paragraph' } }),
      summary: run({ status: 'processing', finished_at: null }),                  // queued: nothing written yet
    })} />)
    expect(screen.queryByText(/paragraph 10/)).toBeNull()
    expect(screen.queryByText(/\//)).toBeNull()
  })
})

describe('StageTable download row (NS-17 item 12)', () => {
  const run = (over: Record<string, unknown>) => ({
    attempt: 1, status: 'done', queue_item_id: 3, model: null, started_at: '2026-11-06T10:00:00', finished_at: '2026-11-06T10:01:00',
    error_code: null, error_text: null, meta: {}, progress_done: null, progress_total: null, runs: 1, last_done: null, ...over,
  })
  const result = (download: unknown) => ({ video_id: 'abc12345678', stages: { download } }) as never

  it('a finished download links to the saved file with its name and size', () => {
    render(<StageTable result={result(run({ meta: { file: 'abc12345678.mp4', size: 5 * 1024 * 1024, format: 'mp4', quality: 'best' } }))} />)
    const link = screen.getByRole('link', { name: /Get the saved file \(abc12345678\.mp4, mp4 best, 5\.0 MB\)/ })
    expect(link.getAttribute('href')).toBe('/api/downloads/abc12345678')
    expect(screen.getByText('Download')).toBeTruthy()
  })

  it('a failed download shows the reason and no link', () => {
    render(<StageTable result={result(run({ status: 'failed', error_code: 'unexpected', error_text: 'yt-dlp failed: ERROR: Video unavailable' }))} />)
    expect(screen.getByText(/Video unavailable/)).toBeTruthy()
    expect(screen.queryByRole('link')).toBeNull()
  })
})

describe('StageTable download reason (review)', () => {
  it('download_failed is shown in plain words', () => {
    const failed = { attempt: 1, status: 'failed', queue_item_id: 3, model: null, started_at: null, finished_at: null,
      error_code: 'download_failed', error_text: 'yt-dlp failed: ERROR: HTTP Error 404: Not Found', meta: {}, progress_done: null,
      progress_total: null, runs: 1, last_done: null }
    render(<StageTable result={{ video_id: 'abc12345678', stages: { download: failed } } as never} />)
    expect(screen.getByText('the download failed')).toBeTruthy()
    expect(screen.getByText(/HTTP Error 404/)).toBeTruthy()
  })
})

describe('StageTable stored file vs the choice now (review)', () => {
  const made = (format: string, quality: string) => ({
    attempt: 1, status: 'done', queue_item_id: 3, model: null, started_at: null, finished_at: null, error_code: null, error_text: null,
    meta: { file: 'abc12345678.mp4', size: 1024, format, quality }, progress_done: null, progress_total: null, runs: 1, last_done: null,
  })
  const table = (run: unknown, chosen?: { format: string; quality: string }) =>
    render(<StageTable result={{ video_id: 'abc12345678', stages: { download: run } } as never} chosenDownload={chosen} />)

  it('says so when the file was made with another format or quality than the choice now', () => {
    table(made('mp4', 'best'), { format: 'mp3', quality: '720p' })
    expect(screen.getByText(/Made as MP4, best; the choice now is MP3, 720p \(not downloaded again by itself\)/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /Get the saved file/ })).toBeTruthy()           // the link is still there
  })

  it('says nothing when they are the same, or when there is no choice to compare with', () => {
    table(made('mp4', 'best'), { format: 'mp4', quality: 'best' })
    expect(screen.queryByText(/Made as/)).toBeNull()
  })

  it('says nothing for an old run without format / quality in its meta', () => {
    table({ ...made('mp4', 'best'), meta: { file: 'abc12345678.mp4', size: 1024 } }, { format: 'mp3', quality: 'best' })
    expect(screen.queryByText(/Made as/)).toBeNull()
  })
})

describe('StageTable link text shows the format and quality (QA)', () => {
  const base = { attempt: 1, status: 'done', queue_item_id: 3, model: null, started_at: null, finished_at: null, error_code: null,
    error_text: null, progress_done: null, progress_total: null, runs: 1, last_done: null }
  const link = (meta: Record<string, unknown>) => {
    render(<StageTable result={{ video_id: 'abc12345678', stages: { download: { ...base, meta } } } as never} />)
    return screen.getByRole('link').textContent
  }

  it('names the format and the quality next to the file', () => {
    expect(link({ file: 'abc12345678.mp4', size: 3 * 1024 * 1024, format: 'mp4', quality: '720p' })).toBe('Get the saved file (abc12345678.mp4, mp4 720p, 3.0 MB)')
  })

  it('an older run without them keeps the short text', () => {
    expect(link({ file: 'abc12345678.mp3', size: 2048 })).toBe('Get the saved file (abc12345678.mp3, 2 KB)')
  })
})
