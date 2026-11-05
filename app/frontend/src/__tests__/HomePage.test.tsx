import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
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

describe('HomePage: a link that is already known (NS-24a)', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it.each([
    ['https://www.youtube.com/live/Ifr9JgTm2TE', 'Ifr9JgTm2TE'],
    ['https://youtu.be/Ifr9JgTm2TE', 'Ifr9JgTm2TE'],
    ['https://www.youtube.com/shorts/Ifr9JgTm2TE', 'Ifr9JgTm2TE'],
  ])('opens /result/<video id> for %s, never /result/<the whole url>', async (url, id) => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 0, ids: [], invalid: [], duplicates: [url],
      duplicate_details: [{ url, video_id: id, reason: 'processed' }],
    })
    await submitUrl(url)
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe(`/result/${id}`))
  })

  it('goes to the queue when the link is already waiting there', async () => {
    const url = 'https://youtu.be/Ifr9JgTm2TE'
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 0, ids: [], invalid: [], duplicates: [url],
      duplicate_details: [{ url, video_id: 'Ifr9JgTm2TE', reason: 'in_queue' }],
    })
    await submitUrl(url)
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/queue'))
  })

  it('goes to the queue after a normal add', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [5], invalid: [], duplicates: [], duplicate_details: [] })
    await submitUrl('https://youtu.be/newVideo001')
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/queue'))
  })
})
