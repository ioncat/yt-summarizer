import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import ProcessingPage from '../pages/ProcessingPage'
import * as api from '../api'

vi.mock('../api', () => ({
  getStatus: vi.fn(),
  processVideo: vi.fn(),
  getResult: vi.fn(),
  startCleanup: vi.fn(),
  startSummary: vi.fn(),
  cancelCleanup: vi.fn(),
  cancelSummary: vi.fn(),
}))

function Where() { return <div data-testid="where">{useLocation().pathname}</div> }

function renderPage(state?: unknown) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/processing/task1/vid1', search: '?url=https%3A%2F%2Fyoutu.be%2Fvid1', state }]}>
      <Routes>
        <Route path="/processing/:taskId/:videoId" element={<><ProcessingPage /><Where /></>} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  )
}

const status = (over: Record<string, unknown>) => ({ task_id: 'task1', status: 'processing', progress: 0, error_message: null,
  available_languages: null, ...over }) as never

describe('ProcessingPage (extraction only; the cleanup/summary chain is gone, NS-11)', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks() })
  afterEach(() => { vi.useRealTimers() })

  it('shows the extraction spinner and the progress text while the task runs', async () => {
    vi.mocked(api.getStatus).mockResolvedValue(status({ progress_text: 'segment 4 · 12%' }))
    renderPage()
    expect(screen.getByText('Extracting subtitles…')).toBeTruthy()
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(screen.getByText('Transcribing…')).toBeTruthy()
    expect(screen.getByText('segment 4 · 12%')).toBeTruthy()
  })

  it('goes to the result page when the task completed', async () => {
    vi.mocked(api.getStatus).mockResolvedValue(status({ status: 'completed' }))
    renderPage()
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(screen.getByTestId('where').textContent).toBe('/result/vid1')
  })

  it('does not start cleanup or summary even when the old autoPipeline flag arrives in the route state', async () => {
    vi.mocked(api.getStatus).mockResolvedValue(status({ status: 'completed' }))
    renderPage({ autoPipeline: true })
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(screen.getByTestId('where').textContent).toBe('/result/vid1')
    expect(api.startCleanup).not.toHaveBeenCalled()
    expect(api.startSummary).not.toHaveBeenCalled()
    expect(screen.queryByText('Stop pipeline')).toBeNull()
  })

  it('shows the failure and offers the available languages; a language retries the extraction', async () => {
    vi.mocked(api.getStatus).mockResolvedValue(status({ status: 'failed', error_message: 'No subtitles in ru', available_languages: ['en', 'uk'] }))
    vi.mocked(api.processVideo).mockResolvedValue({ task_id: 'task2', video_id: 'vid1' })
    renderPage()
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(screen.getByText('Processing Failed')).toBeTruthy()
    expect(screen.getByText('No subtitles in ru')).toBeTruthy()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'English' })) })
    expect(api.processVideo).toHaveBeenCalledWith('https://youtu.be/vid1', 'en')
    expect(screen.getByTestId('where').textContent).toBe('/processing/task2/vid1')
  })

  it('says so when the server cannot be reached', async () => {
    vi.mocked(api.getStatus).mockRejectedValue(new Error('down'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    renderPage()
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(screen.getByText('Could not reach the server')).toBeTruthy()
  })

  it('stops polling when the page is left', async () => {
    vi.mocked(api.getStatus).mockResolvedValue(status({}))
    const view = renderPage()
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    const calls = vi.mocked(api.getStatus).mock.calls.length
    view.unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    expect(vi.mocked(api.getStatus).mock.calls.length).toBe(calls)
  })
})
