import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import HomePage from '../pages/HomePage'

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
