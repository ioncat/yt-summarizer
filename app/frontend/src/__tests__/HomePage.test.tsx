import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
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
  processVideo: vi.fn(),   // (Home no longer calls it: "extract only" goes through the queue, NS-11 stage 7)
  processFile: vi.fn(),
  queueBulkAdd: vi.fn(),
  getQueue: vi.fn(),
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
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(new Error('No answer from the server in 40 s. The link may have been added: check the queue before retrying.'))
    await submitUrl('https://youtu.be/retryHome001')
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('The link may have been added: check the queue before retrying.')
    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({ added: 1, ids: [2], invalid: [], duplicates: [] })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText(/Added to the queue/)).toBeTruthy()
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.queueBulkAdd).mock.calls[1][0]).toEqual(['https://youtu.be/retryHome001'])
    expect(screen.queryByRole('alert')).toBeNull()
  })
})


async function submitExtractOnly(url: string) {
  render(
    <MemoryRouter>
      <Routes>
        <Route path="*" element={<><HomePage /><Where /></>} />
      </Routes>
    </MemoryRouter>
  )
  fireEvent.change(screen.getByPlaceholderText(/youtube\.com\/watch/i), { target: { value: url } })   // the pipeline stays "Extract only"
  fireEvent.submit(screen.getByPlaceholderText(/youtube\.com\/watch/i).closest('form')!)
}

describe('HomePage: "Extract only" is a queue item too (NS-11 stage 7 / NS-24b)', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('adds the link to the queue with the extract stage, never calls the direct /api/process path, and stays on Home', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [7], invalid: [], duplicates: [], duplicate_details: [] })
    await submitExtractOnly('https://youtu.be/extractOnly1')
    expect(await screen.findByText(/Added to the queue/)).toBeTruthy()
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.queueBulkAdd).mock.calls[0][0]).toEqual(['https://youtu.be/extractOnly1'])
    expect(vi.mocked(api.queueBulkAdd).mock.calls[0][1]).toEqual(['extract'])
    expect(api.processVideo).not.toHaveBeenCalled()
    expect(screen.getByTestId('where').textContent).toBe('/')
  })

  it('a link that is already processed shows the "already processed" note with a link to the result, and does not jump', async () => {
    const url = 'https://youtu.be/Ifr9JgTm2TE'
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 0, ids: [], invalid: [], duplicates: [url],
      duplicate_details: [{ url, video_id: 'Ifr9JgTm2TE', reason: 'processed' }],
    })
    await submitExtractOnly(url)
    const link = await screen.findByRole('link', { name: /Open the result/ })
    expect(link.getAttribute('href')).toBe('/result/Ifr9JgTm2TE')
    expect(screen.getByText(/Already processed/)).toBeTruthy()
    expect(screen.getByTestId('where').textContent).toBe('/')
    expect(api.processVideo).not.toHaveBeenCalled()
  })

  it('a link already waiting in the queue says so', async () => {
    const url = 'https://youtu.be/Ifr9JgTm2TE'
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 0, ids: [], invalid: [], duplicates: [url], duplicate_details: [{ url, video_id: 'Ifr9JgTm2TE', reason: 'in_queue' }],
    })
    await submitExtractOnly(url)
    expect(await screen.findByText(/Already in the queue/)).toBeTruthy()
  })

  it('a failed add shows the reason', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(new Error('Failed to add to queue'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    await submitExtractOnly('https://youtu.be/failExtract1')
    expect((await screen.findByRole('alert')).textContent).toContain('Failed to add to queue')
    expect(api.processVideo).not.toHaveBeenCalled()
  })
})


// --- the note follows the queued item (stage 7 QA) ---------------------------------------------------------------------------

const queueItem = (id: number, status: string, extra: Record<string, unknown> = {}) => ({
  id, url: 'https://www.youtube.com/watch?v=follow00001', video_id: 'follow00001', db_video_id: null, status, pipeline_stages: ['extract'],
  error_message: null, added_at: '2026-11-06T10:00:00', started_at: null, finished_at: null, sort_order: id, progress: null, ...extra,
}) as never

function renderHome() {
  return render(
    <MemoryRouter>
      <Routes>
        <Route path="*" element={<><HomePage /><Where /></>} />
      </Routes>
    </MemoryRouter>
  )
}

async function addLink(url: string) {
  fireEvent.change(screen.getByPlaceholderText(/youtube\.com\/watch/i), { target: { value: url } })
  await act(async () => { fireEvent.submit(screen.getByPlaceholderText(/youtube\.com\/watch/i).closest('form')!) })
}

const tick = (ms = 3000) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

describe('HomePage: the note follows the queued item', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks() })
  afterEach(() => { vi.useRealTimers() })

  const added = (id: number) => ({ added: 1, ids: [id], invalid: [], duplicates: [], duplicate_details: [] })

  it('turns "Added to the queue" into "Done" with a link to the result when the item is done, without leaving Home', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue(added(5))
    vi.mocked(api.getQueue).mockResolvedValue({ items: [queueItem(5, 'pending')], count: 1 } as never)
    renderHome()
    await addLink('https://youtu.be/follow00001')
    expect(screen.getByText(/Added to the queue/)).toBeTruthy()
    await tick()
    expect(screen.getByText(/Added to the queue/)).toBeTruthy()                       // still waiting
    vi.mocked(api.getQueue).mockResolvedValue({ items: [queueItem(5, 'processing')], count: 1 } as never)
    await tick()
    expect(screen.getByText(/Added to the queue/)).toBeTruthy()                       // still running
    vi.mocked(api.getQueue).mockResolvedValue({ items: [queueItem(5, 'done')], count: 1 } as never)
    await tick()
    expect(screen.getByText(/Done\./)).toBeTruthy()
    expect(screen.getByRole('link', { name: /Open the result/ }).getAttribute('href')).toBe('/result/follow00001')
    expect(screen.queryByText(/Added to the queue/)).toBeNull()
    expect(screen.getByTestId('where').textContent).toBe('/')
    const calls = vi.mocked(api.getQueue).mock.calls.length
    await tick(10_000)
    expect(vi.mocked(api.getQueue).mock.calls.length).toBe(calls)                      // the poll stopped with the item
  })

  it('turns into "Failed: <reason>" with a link to the queue when the item fails', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue(added(6))
    vi.mocked(api.getQueue).mockResolvedValue({ items: [queueItem(6, 'failed', { error_message: 'This video has no subtitles available.' })], count: 1 } as never)
    renderHome()
    await addLink('https://youtu.be/follow00001')
    await tick()
    expect(screen.getByText(/Failed: This video has no subtitles available\./)).toBeTruthy()
    expect(screen.getByRole('link', { name: /View queue/ }).getAttribute('href')).toBe('/queue')
    expect(screen.getByTestId('where').textContent).toBe('/')
  })

  it('a partly failed item is a failure with its message', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue(added(7))
    vi.mocked(api.getQueue).mockResolvedValue({ items: [queueItem(7, 'partial', { error_message: 'Summary failed: the model returned nothing' })], count: 1 } as never)
    renderHome()
    await addLink('https://youtu.be/follow00001')
    await tick()
    expect(screen.getByText(/Failed: Summary failed: the model returned nothing/)).toBeTruthy()
  })

  it('asks one question at a time: a slow answer is awaited, not overtaken by the next tick', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue(added(8))
    let answer!: (v: never) => void
    vi.mocked(api.getQueue).mockReturnValue(new Promise(res => { answer = res }) as never)
    renderHome()
    await addLink('https://youtu.be/follow00001')
    await tick(3000)
    await tick(9000)
    expect(api.getQueue).toHaveBeenCalledTimes(1)
    answer({ items: [queueItem(8, 'done')], count: 1 } as never)
    await tick(0)
    expect(screen.getByText(/Done\./)).toBeTruthy()
  })

  it('an answer about an earlier link is ignored once another link was added', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce(added(10)).mockResolvedValueOnce(added(11))
    let slow!: (v: never) => void
    vi.mocked(api.getQueue).mockReturnValueOnce(new Promise(res => { slow = res }) as never)
      .mockResolvedValue({ items: [queueItem(10, 'done'), queueItem(11, 'pending')], count: 2 } as never)
    renderHome()
    await addLink('https://youtu.be/follow00001')
    await tick(3000)                                                                   // the question about item 10 is in the air
    await addLink('https://youtu.be/follow00002')                                      // another link: the note now belongs to item 11
    slow({ items: [queueItem(10, 'done')], count: 1 } as never)                        // the old answer arrives late
    await tick(0)
    expect(screen.getByText(/Added to the queue/)).toBeTruthy()
    expect(screen.queryByText(/Done\./)).toBeNull()
  })

  it('stops asking when the page is left', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue(added(12))
    vi.mocked(api.getQueue).mockResolvedValue({ items: [queueItem(12, 'pending')], count: 1 } as never)
    const view = renderHome()
    await addLink('https://youtu.be/follow00001')
    await tick()
    const calls = vi.mocked(api.getQueue).mock.calls.length
    view.unmount()
    await tick(12_000)
    expect(vi.mocked(api.getQueue).mock.calls.length).toBe(calls)
  })

  it('an item taken out of the queue ends the follow without a false "Done"', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue(added(13))
    vi.mocked(api.getQueue).mockResolvedValue({ items: [], count: 0 } as never)
    renderHome()
    await addLink('https://youtu.be/follow00001')
    await tick()
    expect(screen.queryByText(/Done\./)).toBeNull()
    const calls = vi.mocked(api.getQueue).mock.calls.length
    await tick(9000)
    expect(vi.mocked(api.getQueue).mock.calls.length).toBe(calls)
  })

  it('a failed poll request is tried again at the next tick', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue(added(14))
    vi.mocked(api.getQueue).mockRejectedValueOnce(new Error('network')).mockResolvedValue({ items: [queueItem(14, 'done')], count: 1 } as never)
    renderHome()
    await addLink('https://youtu.be/follow00001')
    await tick()
    expect(screen.getByText(/Added to the queue/)).toBeTruthy()
    await tick()
    expect(screen.getByText(/Done\./)).toBeTruthy()
  })

  it('a link that is already processed has nothing to follow', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 0, ids: [], invalid: [], duplicates: ['https://youtu.be/follow00001'],
      duplicate_details: [{ url: 'https://youtu.be/follow00001', video_id: 'follow00001', reason: 'processed' }],
    })
    renderHome()
    await addLink('https://youtu.be/follow00001')
    await tick(9000)
    expect(api.getQueue).not.toHaveBeenCalled()
  })
})
