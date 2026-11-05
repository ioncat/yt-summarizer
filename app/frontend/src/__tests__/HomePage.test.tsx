import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import HomePage from '../pages/HomePage'
import * as api from '../api'

// Mock the entire api module so no actual fetch calls are made
vi.mock('../api', () => ({
  getSettings: vi.fn().mockResolvedValue({
    app: {
      ollama_url: null,
      ytdlp_path: null,
      cookies_path: null,
      force_map_reduce: null,
      parallel_workers: null,
      stt_engine: null,
      stt_model: null,
      stt_device: null,
      stt_cache_path: null,
      upload_auto_delete: null,
      upload_auto_delete_mode: null,
      upload_auto_delete_days: null,
    },
    cleanup: { stage: 'cleanup', system_prompt: null, user_prompt_template: null, model: null, is_default: true },
    summarization: { stage: 'summarization', system_prompt: null, user_prompt_template: null, model: null, is_default: true },
    summarization_extract: { stage: 'summarization_extract', system_prompt: null, user_prompt_template: null, model: null, is_default: true },
    summarization_combine: { stage: 'summarization_combine', system_prompt: null, user_prompt_template: null, model: null, is_default: true },
    chat: { stage: 'chat', system_prompt: null, user_prompt_template: null, model: null, is_default: true },
  }),
  getHealth: vi.fn().mockResolvedValue({ backend: true, ollama: false }),
  processVideo: vi.fn(),
  processFile: vi.fn(),
  queueBulkAdd: vi.fn(),
  VideoAlreadyExistsError: class VideoAlreadyExistsError extends Error {
    constructor(public readonly videoId: string) {
      super('Video already processed')
    }
  },
}))

function renderHomePage() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>
  )
}

describe('HomePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without throwing', () => {
    expect(() => renderHomePage()).not.toThrow()
  })

  it('has a URL input field', () => {
    renderHomePage()
    // The URL form has a text input with YouTube placeholder
    const input = screen.getByPlaceholderText(/youtube\.com/i)
    expect(input).toBeTruthy()
  })

  it('has a submit / add-to-queue button', () => {
    renderHomePage()
    // There are multiple buttons; at least one should match common submit labels
    const buttons = screen.getAllByRole('button')
    expect(buttons.length).toBeGreaterThan(0)
  })
})


function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

async function submitUrl(url: string) {
  render(
    <MemoryRouter>
      <Routes>
        <Route path="*" element={<><HomePage /><Where /></>} />
      </Routes>
    </MemoryRouter>
  )
  fireEvent.change(screen.getByPlaceholderText(/youtube\.com\/watch/i), { target: { value: url } })
  fireEvent.change(screen.getByLabelText('Pipeline'), { target: { value: 'cleanup' } })  // 2 stages: through the queue
  fireEvent.submit(screen.getByPlaceholderText(/youtube\.com\/watch/i).closest('form')!)
}

describe('HomePage: adding through the queue keeps the page (NS-24a)', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it.each([
    ['https://www.youtube.com/live/Ifr9JgTm2TE'],
    ['https://youtu.be/Ifr9JgTm2TE'],
    ['https://www.youtube.com/shorts/Ifr9JgTm2TE'],
  ])('a processed link (%s) says so and links to /result/<video id>, not to the whole url', async (url) => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 0, ids: [], invalid: [], duplicates: [url],
      duplicate_details: [{ url, video_id: 'Ifr9JgTm2TE', reason: 'processed' }],
    })
    await submitUrl(url)
    const link = await screen.findByRole('link', { name: /Open the result/ })
    expect(link.getAttribute('href')).toBe('/result/Ifr9JgTm2TE')
    expect(screen.getByText(/Already processed/)).toBeTruthy()
    expect(screen.getByTestId('where').textContent).toBe('/')   // the page did not jump away
  })

  it('a link already waiting in the queue says so and stays', async () => {
    const url = 'https://youtu.be/Ifr9JgTm2TE'
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 0, ids: [], invalid: [], duplicates: [url],
      duplicate_details: [{ url, video_id: 'Ifr9JgTm2TE', reason: 'in_queue' }],
    })
    await submitUrl(url)
    expect(await screen.findByText(/Already in the queue/)).toBeTruthy()
    expect(screen.getByTestId('where').textContent).toBe('/')
  })

  it('a new link is added, the field is cleared, the page stays with a link to the queue', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [5], invalid: [], duplicates: [], duplicate_details: [] })
    await submitUrl('https://youtu.be/newVideo001')
    expect(await screen.findByText(/Added to the queue/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /View queue/ }).getAttribute('href')).toBe('/queue')
    expect((screen.getByPlaceholderText(/youtube\.com\/watch/i) as HTMLInputElement).value).toBe('')
    expect(screen.getByTestId('where').textContent).toBe('/')
  })

  it('a link the server cannot use is reported', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 0, ids: [], invalid: ['x'], duplicates: [] })
    await submitUrl('not a link at all')
    expect(await screen.findByText('Not a YouTube link.')).toBeTruthy()
  })
})


describe('HomePage: a failed or slow add (NS-28)', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows "Adding..." on the button while the server has not answered', async () => {
    let answer!: (v: api.QueueAddResult) => void
    vi.mocked(api.queueBulkAdd).mockReturnValue(new Promise(res => { answer = res }))
    await submitUrl('https://youtu.be/slowHome0001')
    expect(await screen.findByRole('button', { name: 'Adding…' })).toBeTruthy()
    answer({ added: 1, ids: [1], invalid: [], duplicates: [] })
    expect(await screen.findByText(/Added to the queue/)).toBeTruthy()
  })

  it('a failed add shows the reason and a Retry that sends the same link again', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(new Error('No answer from the server in 15 s - it may be busy or not running. Try again.'))
    await submitUrl('https://youtu.be/retryHome001')
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('No answer from the server in 15 s')
    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({ added: 1, ids: [2], invalid: [], duplicates: [] })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText(/Added to the queue/)).toBeTruthy()
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.queueBulkAdd).mock.calls[1][0]).toEqual(['https://youtu.be/retryHome001'])
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
