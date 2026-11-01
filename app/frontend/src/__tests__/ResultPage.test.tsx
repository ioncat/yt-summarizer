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

  it('Cleaned tab: empty state and Clean with AI queues cleanup', async () => {
    await renderPage()
    fireEvent.click(btn('Cleaned'))
    expect(screen.getByText(/No cleaned version yet/)).toBeTruthy()
    fireEvent.click(btn(/Clean with AI/))
    await waitFor(() => expect(m.queueBulkAdd).toHaveBeenCalledWith([base.url], ['cleanup'], true))
    expect(await screen.findByText(/Added to queue/)).toBeTruthy()
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

  it('Summary tab: Summarize with cleanup done queues summary', async () => {
    setResult({ cleanup_status: 'done', cleaned_text: 'c' })
    await renderPage()
    fireEvent.click(btn('Summary'))
    expect(screen.getByText(/No summary yet/)).toBeTruthy()
    fireEvent.click(btn(/Summarize/))
    await waitFor(() => expect(m.queueBulkAdd).toHaveBeenCalledWith([base.url], ['summary'], true))
  })

  it('Mind Map tab: empty state and Generate queues mindmap', async () => {
    await renderPage()
    fireEvent.click(btn('Mind Map'))
    expect(screen.getByText(/No mind map yet/)).toBeTruthy()
    fireEvent.click(btn(/Generate mind map/))
    await waitFor(() => expect(m.queueBulkAdd).toHaveBeenCalledWith([base.url], ['mindmap'], true))
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
})
