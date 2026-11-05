import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ResultPage from '../pages/ResultPage'
import * as api from '../api'

vi.mock('react-markdown', () => ({ default: ({ children }: { children: string }) => <div>{children}</div> }))
vi.mock('../components/MindmapView', () => ({
  default: ({ text }: { text: string }) => <div data-testid="mindmap-view">{text}</div>,
}))

vi.mock('../api', () => ({
  getResult: vi.fn(),
  deleteResult: vi.fn(),
  startCleanup: vi.fn(),
  cancelCleanup: vi.fn(),
  startSummary: vi.fn(),
  cancelSummary: vi.fn(),
  startMindmap: vi.fn(),
  cancelMindmap: vi.fn(),
  reextractSubtitles: vi.fn(),
  saveChatHistory: vi.fn(),
  clearChatHistory: vi.fn(),
  getSettings: vi.fn(),
  getModels: vi.fn(),
  saveSettings: vi.fn(),
  saveAppSettings: vi.fn(),
  getSttModels: vi.fn(),
  queueBulkAdd: vi.fn(),
  queueBulkAddByIds: vi.fn(),
  toggleFavorite: vi.fn(),
  downloadVideo: vi.fn(),
}))

const m = vi.mocked(api)

const base = {
  video_id: 'abc123',
  url: 'https://www.youtube.com/watch?v=abc123',
  title: 'Test Video',
  author: 'Some Channel',
  duration: 125,
  language: 'en',
  created_at: '2026-01-02 10:30:00',
  is_favorite: false,
  char_count: 1234,
  formatted_text: 'Formatted subtitle text',
  cleaned_text: null,
  summary_text: null,
  mindmap_text: null,
  cleanup_status: null,
  summary_status: null,
  mindmap_status: null,
  subtitle_source: 'subtitles',
  subtitles_type: 'automatic_captions',
  chat_history: [],
}

function setResult(over: Record<string, unknown> = {}) {
  m.getResult.mockResolvedValue({ ...base, ...over } as never)
}

async function renderPage() {
  render(
    <MemoryRouter initialEntries={['/result/abc123']}>
      <Routes>
        <Route path="/result/:videoId" element={<ResultPage />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByText('Test Video')
}

const btn = (name: string | RegExp) => screen.getByRole('button', { name })

describe('ResultPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setResult()
    m.getSettings.mockResolvedValue({
      app: { ollama_url: 'http://localhost:11434', stt_model: 'base', download_default_format: 'mp4', download_default_quality: 'best' },
      cleanup: { model: 'llama3', system_prompt: null, user_prompt_template: null },
      summarization: { model: 'llama3', system_prompt: null, user_prompt_template: null },
      chat: { model: 'llama3' },
    } as never)
    m.getModels.mockResolvedValue(['llama3', 'qwen3'])
    m.getSttModels.mockResolvedValue([{ name: 'base', downloaded: true }] as never)
    m.queueBulkAdd.mockResolvedValue({} as never)
    m.cancelCleanup.mockResolvedValue(undefined as never)
    m.cancelSummary.mockResolvedValue(undefined as never)
    m.cancelMindmap.mockResolvedValue(undefined as never)
    m.deleteResult.mockResolvedValue(undefined as never)
    m.downloadVideo.mockResolvedValue(undefined as never)
  })

  afterEach(() => cleanup())

  it('shows header, meta and tab bar in order', async () => {
    await renderPage()
    expect(screen.getByText('Some Channel')).toBeTruthy()
    expect(screen.getByText('2:05')).toBeTruthy()
    expect(screen.getByText('EN')).toBeTruthy()
    const labels = ['Mind Map', 'Subtitles', 'Cleaned', 'Summary']
    const tabs = screen.getAllByRole('button').map(b => b.textContent).filter(t => labels.includes(t ?? ''))
    expect(tabs).toEqual(labels)
  })

  it('Subtitles tab: text, ribbon and action bar for a video', async () => {
    await renderPage()
    expect(screen.getByText('Formatted subtitle text')).toBeTruthy()
    expect(screen.getByText('Auto-captions')).toBeTruthy()
    expect(btn(/Re-extract/)).toBeTruthy()
    expect(screen.getByText('Open video')).toBeTruthy()
    expect(screen.getByText('Benchmark')).toBeTruthy()
    expect(btn(/Download/)).toBeTruthy()
    expect(btn(/Copy text/)).toBeTruthy()
    expect(btn(/Delete/)).toBeTruthy()
  })

  it('file result: no Open video, Benchmark or Download; Re-transcribe shown', async () => {
    setResult({ video_id: 'file-1234', url: 'local://talk.mp3', subtitle_source: 'transcript', subtitles_type: null })
    await renderPage()
    expect(screen.queryByText('Open video')).toBeNull()
    expect(screen.queryByText('Benchmark')).toBeNull()
    expect(screen.queryByRole('button', { name: /Download/ })).toBeNull()
    expect(btn(/Re-transcribe/)).toBeTruthy()
    expect(screen.getByText('Whisper transcript')).toBeTruthy()
  })

  it('Cleaned tab: empty state and Clean with AI queues the cleanup through the endpoint (one path, NS-11 stage 4a)', async () => {
    m.startCleanup.mockResolvedValue(undefined as never)
    await renderPage()
    fireEvent.click(btn('Cleaned'))
    expect(screen.getByText(/No cleaned version yet/)).toBeTruthy()
    fireEvent.click(btn(/Clean with AI/))
    await waitFor(() => expect(m.startCleanup).toHaveBeenCalledWith(base.video_id))
    expect(m.queueBulkAdd).not.toHaveBeenCalledWith(expect.anything(), ['cleanup'], expect.anything())  // not the URL queue path
    expect(await screen.findByText(/Added to queue/)).toBeTruthy()
  })

  it('Cleaned tab: a local file uses the same endpoint', async () => {
    m.startCleanup.mockResolvedValue(undefined as never)
    setResult({ video_id: 'file-1234', url: 'local://talk.mp3', subtitle_source: 'transcript', subtitles_type: null })
    await renderPage()
    fireEvent.click(btn('Cleaned'))
    fireEvent.click(btn(/Clean with AI/))
    await waitFor(() => expect(m.startCleanup).toHaveBeenCalledWith(base.video_id))    // the page's route id
    expect(m.queueBulkAdd).not.toHaveBeenCalledWith(expect.anything(), ['cleanup'], expect.anything())
  })

  it('Cleaned tab: Re-run AI cleanup uses the endpoint too', async () => {
    m.startCleanup.mockResolvedValue(undefined as never)
    setResult({ cleanup_status: 'done', cleaned_text: 'old cleaned' })
    await renderPage()
    fireEvent.click(btn('Cleaned'))
    fireEvent.click(btn(/Re-run AI cleanup/))
    await waitFor(() => expect(m.startCleanup).toHaveBeenCalledWith(base.video_id))
  })

  it('Cleaned tab: the endpoint\'s refusal (no model configured) is shown with its reason', async () => {
    m.startCleanup.mockRejectedValue(new Error('No model configured. Please select a model in Settings first.'))
    await renderPage()
    fireEvent.click(btn('Cleaned'))
    fireEvent.click(btn(/Clean with AI/))
    expect((await screen.findAllByText(/No model configured/)).length).toBeGreaterThan(0)
  })

  it('Cleaned tab: processing shows Stop which cancels cleanup', async () => {
    setResult({ cleanup_status: 'processing' })
    await renderPage()
    fireEvent.click(btn(/Cleaned/))
    fireEvent.click(await screen.findByRole('button', { name: /Stop/ }))
    await waitFor(() => expect(m.cancelCleanup).toHaveBeenCalledWith('abc123'))
  })

  it('Cleaned tab: done shows cleaned text and Re-run button', async () => {
    setResult({ cleanup_status: 'done', cleaned_text: 'Cleaned paragraph one', cleanup_duration_seconds: 30, cleanup_model: 'llama3' })
    await renderPage()
    fireEvent.click(btn('Cleaned'))
    expect(screen.getByText('Cleaned paragraph one')).toBeTruthy()
    expect(btn(/Re-run AI cleanup/)).toBeTruthy()
    expect(screen.getByText(/Cleaned in 0:30/)).toBeTruthy()
  })

  it('Summary tab: opens by default when summary exists; Re-run and Stop', async () => {
    setResult({ summary_status: 'done', summary_text: 'The summary body', summary_duration_seconds: 10, summary_mode: 'single' })
    await renderPage()
    expect(screen.getByText('The summary body')).toBeTruthy()
    expect(btn(/Re-run summary/)).toBeTruthy()
    expect(screen.getByText('Single Pass')).toBeTruthy()
  })

  it('Summary tab: processing Stop cancels summary', async () => {
    setResult({ summary_status: 'processing' })
    await renderPage()
    fireEvent.click(btn(/Summary/))
    fireEvent.click(await screen.findByRole('button', { name: /Stop/ }))
    await waitFor(() => expect(m.cancelSummary).toHaveBeenCalledWith('abc123'))
  })

  it('Summary tab: Summarize with cleanup done queues the summary through the endpoint (one path, NS-11 stage 3)', async () => {
    m.startSummary.mockResolvedValue(undefined as never)
    setResult({ cleanup_status: 'done', cleaned_text: 'c' })
    await renderPage()
    fireEvent.click(btn('Summary'))
    expect(screen.getByText(/No summary yet/)).toBeTruthy()
    fireEvent.click(btn(/Summarize/))
    await waitFor(() => expect(m.startSummary).toHaveBeenCalledWith(base.video_id))
    expect(m.queueBulkAdd).not.toHaveBeenCalledWith(expect.anything(), ['summary'], expect.anything())  // not the URL queue path
  })

  it('Summarize before any cleanup: after the confirm ONE item with both stages is queued by the video id', async () => {
    m.queueBulkAddByIds.mockResolvedValue({ added: 1, ids: [5], invalid: [], duplicates: [], missing: [] })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await renderPage()                                             // base: no cleanup yet
    fireEvent.click(btn('Summary'))
    fireEvent.click(btn(/Summarize/))
    await waitFor(() => expect(m.queueBulkAddByIds).toHaveBeenCalledWith([base.video_id], ['cleanup', 'summary']))
    expect(m.startCleanup).not.toHaveBeenCalled()                  // no client-side chain any more
    expect(m.queueBulkAdd).not.toHaveBeenCalled()
    expect(await screen.findByText(/cleanup → summary/)).toBeTruthy()
  })

  it('Summarize before any cleanup: a local file takes the same path (no URL needed)', async () => {
    m.queueBulkAddByIds.mockResolvedValue({ added: 1, ids: [5], invalid: [], duplicates: [], missing: [] })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    setResult({ video_id: 'file-1234', url: 'local://talk.mp3', subtitle_source: 'transcript', subtitles_type: null })
    await renderPage()
    fireEvent.click(btn('Summary'))
    fireEvent.click(btn(/Summarize/))
    await waitFor(() => expect(m.queueBulkAddByIds).toHaveBeenCalledWith([base.video_id], ['cleanup', 'summary']))
  })

  it('Summarize before any cleanup: declining the confirm queues nothing', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    await renderPage()
    fireEvent.click(btn('Summary'))
    fireEvent.click(btn(/Summarize/))
    expect(m.queueBulkAddByIds).not.toHaveBeenCalled()
  })

  it('Summarize before any cleanup: a video that already has a queue item says so instead of showing "queued"', async () => {
    m.queueBulkAddByIds.mockResolvedValue({ added: 0, ids: [], invalid: [], duplicates: [base.video_id], missing: [] })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await renderPage()
    fireEvent.click(btn('Summary'))
    fireEvent.click(btn(/Summarize/))
    expect((await screen.findAllByText(/already has an item in the queue/)).length).toBeGreaterThan(0)
    expect(screen.queryByText(/cleanup → summary/)).toBeNull()
  })

  it('Summarize before any cleanup: when stages are already queued the message names them (NS-25)', async () => {
    m.queueBulkAddByIds.mockResolvedValue({ added: 0, ids: [], invalid: [], duplicates: [base.video_id], missing: [],
      duplicate_details: [{ url: null, video_id: base.video_id, reason: 'in_queue', stages: ['cleanup', 'summary'] }] })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await renderPage()
    fireEvent.click(btn('Summary'))
    fireEvent.click(btn(/Summarize/))
    expect((await screen.findAllByText(/cleanup and summary are already in the queue/)).length).toBeGreaterThan(0)
  })

  it('Summary: a local file uses the same endpoint', async () => {
    m.startSummary.mockResolvedValue(undefined as never)
    setResult({ video_id: 'file-1234', url: 'local://talk.mp3', subtitle_source: 'transcript', subtitles_type: null,
                cleanup_status: 'done', cleaned_text: 'c' })
    await renderPage()
    fireEvent.click(btn('Summary'))
    fireEvent.click(btn(/Summarize/))
    await waitFor(() => expect(m.startSummary).toHaveBeenCalledWith(base.video_id))   // the page's route id
    expect(m.queueBulkAdd).not.toHaveBeenCalledWith(expect.anything(), ['summary'], expect.anything())
  })

  it('Summary: Re-run summary uses the endpoint too', async () => {
    m.startSummary.mockResolvedValue(undefined as never)
    setResult({ cleanup_status: 'done', cleaned_text: 'c', summary_status: 'done', summary_text: 'old summary' })
    await renderPage()
    fireEvent.click(btn('Summary'))
    fireEvent.click(btn(/Re-run summary/))
    await waitFor(() => expect(m.startSummary).toHaveBeenCalledWith(base.video_id))
  })

  it('Summary: the endpoint\'s refusal (no model configured) is shown with its reason', async () => {
    m.startSummary.mockRejectedValue(new Error('No summarization model configured. Please select one in Settings → Summarization.'))
    setResult({ cleanup_status: 'done', cleaned_text: 'c' })
    await renderPage()
    fireEvent.click(btn('Summary'))
    fireEvent.click(btn(/Summarize/))
    expect((await screen.findAllByText(/No summarization model configured/)).length).toBeGreaterThan(0)
  })

  it('Mind Map tab: empty state and Generate queues the mind map through the endpoint (one path, NS-11 stage 2)', async () => {
    m.startMindmap.mockResolvedValue({ status: 'processing' } as never)
    await renderPage()
    fireEvent.click(btn('Mind Map'))
    expect(screen.getByText(/No mind map yet/)).toBeTruthy()
    fireEvent.click(btn(/Generate mind map/))
    await waitFor(() => expect(m.startMindmap).toHaveBeenCalledWith(base.video_id, false))
    expect(m.queueBulkAdd).not.toHaveBeenCalledWith(expect.anything(), ['mindmap'], expect.anything())  // not the URL queue path
  })

  it('Mind Map: a local file uses the same endpoint', async () => {
    m.startMindmap.mockResolvedValue({ status: 'processing' } as never)
    setResult({ video_id: 'file-1234', url: 'local://talk.mp3', subtitle_source: 'transcript', subtitles_type: null })
    await renderPage()
    fireEvent.click(btn('Mind Map'))
    fireEvent.click(btn(/Generate mind map/))
    await waitFor(() => expect(m.startMindmap).toHaveBeenCalledWith(base.video_id, false))  // the page's route id
    expect(m.queueBulkAdd).not.toHaveBeenCalledWith(expect.anything(), ['mindmap'], expect.anything())
  })

  it('Mind Map: Regenerate sends force=true', async () => {
    m.startMindmap.mockResolvedValue({ status: 'processing' } as never)
    setResult({ mindmap_text: '# Root', mindmap_status: 'done' })
    await renderPage()
    fireEvent.click(btn(/Regenerate mind map/))
    await waitFor(() => expect(m.startMindmap).toHaveBeenCalledWith(base.video_id, true))
  })

  it('Mind Map: when the server hands back the saved map it is shown and nothing is polled', async () => {
    m.startMindmap.mockResolvedValue({ status: 'done', mindmap_text: '# Saved map' } as never)
    setResult({ mindmap_text: null, mindmap_status: null })
    await renderPage()
    fireEvent.click(btn('Mind Map'))
    fireEvent.click(btn(/Generate mind map/))
    expect((await screen.findByTestId('mindmap-view')).textContent).toBe('# Saved map')
    expect(screen.queryByText(/queued/i)).toBeNull()
  })

  it('Mind Map: after a failed regeneration the saved map is shown with the error above it', async () => {
    setResult({ mindmap_text: '# Saved map', mindmap_status: 'failed', mindmap_error: 'model returned nothing' })
    await renderPage()
    fireEvent.click(btn('Mind Map'))
    expect((await screen.findByTestId('mindmap-view')).textContent).toBe('# Saved map')
    expect(screen.getAllByText(/model returned nothing/).length).toBeGreaterThan(0)
    expect(btn(/Regenerate mind map/)).toBeTruthy()
  })

  it('Mind Map: a failed first run (no saved map) shows only the error', async () => {
    setResult({ mindmap_text: null, mindmap_status: 'failed', mindmap_error: 'model returned nothing' })
    await renderPage()
    fireEvent.click(btn('Mind Map'))
    expect(screen.getAllByText(/model returned nothing/).length).toBeGreaterThan(0)
    expect(screen.queryByTestId('mindmap-view')).toBeNull()
  })

  it('Mind Map: Regenerate does not clear the map before the server has accepted the request', async () => {
    let answer!: (v: { status: string }) => void
    m.startMindmap.mockReturnValue(new Promise(res => { answer = res }) as never)
    setResult({ mindmap_text: '# Saved map', mindmap_status: 'done' })
    await renderPage()
    fireEvent.click(btn(/Regenerate mind map/))
    await waitFor(() => expect(m.startMindmap).toHaveBeenCalledWith(base.video_id, true))
    expect(screen.getByTestId('mindmap-view').textContent).toBe('# Saved map')     // still there while the request is out
    answer({ status: 'processing' })
    expect(await screen.findByText('Regenerating…')).toBeTruthy()                  // accepted: the label, and the map stays
    expect(screen.getByTestId('mindmap-view').textContent).toBe('# Saved map')
  })

  it('Mind Map: while a regeneration runs the saved map stays on screen under a "Regenerating…" label, with Stop', async () => {
    setResult({ mindmap_text: '# Saved map', mindmap_status: 'processing' })
    await renderPage()                                                  // the page opens on the Mind Map tab when a map exists
    expect((await screen.findByTestId('mindmap-view')).textContent).toBe('# Saved map')
    expect(screen.getByText('Regenerating…')).toBeTruthy()
    expect(btn(/Stop/)).toBeTruthy()
    expect(screen.queryByText('Generating mind map…')).toBeNull()      // the bare spinner is for "no map yet" only
  })

  it('Mind Map: the first generation (no saved map yet) still shows the bare "Generating mind map…"', async () => {
    setResult({ mindmap_text: null, mindmap_status: 'processing' })
    await renderPage()
    fireEvent.click(btn(/Mind Map/))                                    // its label has a "…" while processing
    expect(await screen.findByText('Generating mind map…')).toBeTruthy()
    expect(screen.queryByTestId('mindmap-view')).toBeNull()
    expect(screen.queryByText('Regenerating…')).toBeNull()
  })

  it('Mind Map: the map is not lost on the way: Regenerate click -> request out -> accepted -> still the old map under the label', async () => {
    m.startMindmap.mockResolvedValue({ status: 'processing' } as never)
    setResult({ mindmap_text: '# Saved map', mindmap_status: 'done' })
    await renderPage()
    fireEvent.click(btn(/Regenerate mind map/))
    expect(await screen.findByText('Regenerating…')).toBeTruthy()
    expect(screen.getByTestId('mindmap-view').textContent).toBe('# Saved map')
  })

  it('Mind Map: a refused Regenerate (503) leaves the saved map in place with the reason', async () => {
    m.startMindmap.mockRejectedValue(new Error('database busy, try again'))
    setResult({ mindmap_text: '# Saved map', mindmap_status: 'done' })
    await renderPage()
    fireEvent.click(btn(/Regenerate mind map/))
    expect((await screen.findAllByText(/database busy, try again/)).length).toBeGreaterThan(0)
    expect(screen.getByTestId('mindmap-view').textContent).toBe('# Saved map')
  })

  it('Mind Map: a failure to queue shows the reason', async () => {
    m.startMindmap.mockRejectedValue(new Error('database busy, try again'))
    await renderPage()
    fireEvent.click(btn('Mind Map'))
    fireEvent.click(btn(/Generate mind map/))
    expect((await screen.findAllByText(/database busy, try again/)).length).toBeGreaterThan(0)
  })

  it('Mind Map tab: shows mindmap view when text exists', async () => {
    setResult({ mindmap_text: '# Root', mindmap_status: 'done' })
    await renderPage()
    expect(await screen.findByTestId('mindmap-view')).toBeTruthy()
    expect(btn(/Regenerate mind map/)).toBeTruthy()
  })

  it('Chat tab: history, Clear chat and input bar', async () => {
    setResult({
      summary_status: 'done', summary_text: 'sum',
      chat_history: [{ role: 'user', content: 'What is it?' }, { role: 'assistant', content: 'A test.' }],
    })
    await renderPage()
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('button', { name: /Chat/ }))
    expect(screen.getByText('What is it?')).toBeTruthy()
    expect(screen.getByText('A test.')).toBeTruthy()
    expect(btn(/Copy chat/)).toBeTruthy()
    expect(btn(/Clear chat/)).toBeTruthy()
    expect(await screen.findByPlaceholderText('Ask about the video…')).toBeTruthy()
  })

  it('failed stages show the stored reason; without one the generic text stays', async () => {
    setResult({ summary_status: 'failed', summary_error: 'model returned no answer (thinking used the whole context)' })
    await renderPage()
    fireEvent.click(btn('Summary'))
    expect(screen.getByText('model returned no answer (thinking used the whole context)')).toBeTruthy()
    expect(screen.queryByText(/Possible causes: Ollama not running/)).toBeNull()
  })

  it('failed cleanup shows the stored reason; without one the generic text stays', async () => {
    setResult({ cleanup_status: 'failed', cleanup_error: 'model returned nothing' })
    await renderPage()
    fireEvent.click(btn('Cleaned'))
    expect(screen.getByText('model returned nothing')).toBeTruthy()
    expect(screen.queryByText(/Possible causes: Ollama not running/)).toBeNull()
    cleanup()
    setResult({ cleanup_status: 'failed', cleanup_error: null })
    await renderPage()
    fireEvent.click(btn('Cleaned'))
    expect(screen.getByText(/Possible causes: Ollama not running/)).toBeTruthy()
  })

  it('failed summary without a stored reason keeps the generic text', async () => {
    setResult({ summary_status: 'failed', summary_error: null })
    await renderPage()
    fireEvent.click(btn('Summary'))
    expect(screen.getByText(/Possible causes: Ollama not running/)).toBeTruthy()
  })

  it('failed mind map shows the stored reason (banner and tab body)', async () => {
    setResult({ mindmap_status: 'failed', mindmap_error: 'model returned nothing' })
    await renderPage()
    fireEvent.click(btn('Mind Map'))
    expect(screen.getAllByText('model returned nothing').length).toBeGreaterThan(0)
    expect(screen.queryByText(/Check Ollama and model settings/)).toBeNull()
  })

  it('Delete asks for confirmation and calls deleteResult', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await renderPage()
    fireEvent.click(btn(/Delete/))
    await waitFor(() => expect(m.deleteResult).toHaveBeenCalledWith('abc123'))
  })

  it('Download calls downloadVideo with chosen format and quality', async () => {
    await renderPage()
    fireEvent.click(btn(/Download/))
    await waitFor(() => expect(m.downloadVideo).toHaveBeenCalledWith('abc123', 'mp4', 'best'))
  })

  it('shows the stage table when the result has recorded runs, and not otherwise (NS-25)', async () => {
    await renderPage()
    expect(screen.queryByText(/Processing steps/)).toBeNull()
    cleanup()
    setResult({ stages: { summary: {
      attempt: 2, status: 'failed', queue_item_id: 1, model: 'bad', started_at: null, finished_at: '2026-11-01T10:00:00',
      error_code: 'timeout', error_text: 'Read timed out', meta: {}, progress_done: null, progress_total: null, runs: 2,
      last_done: { attempt: 1, status: 'done', queue_item_id: 1, model: 'good', started_at: null, finished_at: '2026-11-01T09:00:00',
        error_code: null, error_text: null, meta: {}, progress_done: null, progress_total: null },
    } } })
    await renderPage()
    expect(await screen.findByText(/Processing steps \(1\)/)).toBeTruthy()
    expect(screen.getByText('timed out')).toBeTruthy()
    expect(screen.getByText('good')).toBeTruthy()
  })
})
