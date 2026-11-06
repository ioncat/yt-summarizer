import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
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
  queueBulkAddByIds: vi.fn(),
  getQueue: vi.fn(),
  InvalidLinkError: class InvalidLinkError extends Error {
    constructor(public invalid: string[] = [], public report: unknown[] = []) { super('No valid YouTube URLs') }
  },
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


// --- the list form is the main add form (NS-24a, NS-17 item 4) ---------------------------------------------------------------

describe('HomePage: one form for one link or a list', () => {
  const field = () => screen.getByPlaceholderText(/youtube\.com\/watch/i) as HTMLTextAreaElement

  function renderHome() {
    return render(
      <MemoryRouter>
        <Routes>
          <Route path="*" element={<><HomePage /><Where /></>} />
        </Routes>
      </MemoryRouter>
    )
  }

  const list = ['https://youtu.be/listVideo001', 'https://youtu.be/listVideo002', 'https://youtu.be/listVideo003']

  beforeEach(() => { vi.clearAllMocks() })

  it('the field takes several lines: a textarea, with the list form always on the page (no separate Bulk add)', () => {
    renderHome()
    expect(field().tagName).toBe('TEXTAREA')
    expect(screen.queryByRole('button', { name: /Bulk add/ })).toBeNull()
    expect(screen.getByText(/one per line/)).toBeTruthy()
  })

  it('a list is sent as separate links in the order typed, with the Home pipeline choice and language, and the field is cleared', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 3, ids: [1, 2, 3], invalid: [], duplicates: [], duplicate_details: [] })
    renderHome()
    fireEvent.change(screen.getByLabelText('Pipeline'), { target: { value: 'cleanup' } })
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'ru' } })
    fireEvent.change(field(), { target: { value: list.join('\n') } })
    expect(screen.getByText('3 links detected')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Add all (3)' }))
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalledTimes(1))
    const [urls, stages, force, language] = vi.mocked(api.queueBulkAdd).mock.calls[0]
    expect(urls).toEqual(list)                                    // newlines no longer glue the links together
    expect(stages).toEqual(['extract', 'cleanup'])
    expect(force).toBe(false)
    expect(language).toBe('ru')
    expect(await screen.findByText(/Added/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /View queue/ }).getAttribute('href')).toBe('/queue')
    expect(field().value).toBe('')
    expect(screen.getByTestId('where').textContent).toBe('/')
  })

  it('"URL | title" lines, blank lines and Windows line ends give clean links', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 2, ids: [1, 2], invalid: [], duplicates: [] })
    renderHome()
    fireEvent.change(field(), { target: { value: `${list[0]} | My title\r\n\r\n  ${list[1]},\r\n` } })
    fireEvent.click(screen.getByRole('button', { name: 'Add all (2)' }))
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalled())
    expect(vi.mocked(api.queueBulkAdd).mock.calls[0][0]).toEqual([list[0], list[1]])
  })

  it('a list where nothing was added says so, names each link\'s reason, and keeps the text for editing', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 0, ids: [], invalid: ['nonsense'], duplicates: [list[0]],
      duplicate_details: [{ url: list[0], video_id: 'listVideo001', reason: 'processed' }],
      report: [
        { url: list[0], video_id: 'listVideo001', status: 'processed' },
        { url: 'nonsense', video_id: null, status: 'invalid' },
      ],
    })
    renderHome()
    fireEvent.change(field(), { target: { value: `${list[0]}\nnonsense` } })
    fireEvent.click(screen.getByRole('button', { name: 'Add all (2)' }))
    expect(await screen.findByText(/Nothing was added/)).toBeTruthy()
    expect(screen.getByText('already processed')).toBeTruthy()
    expect(screen.getByText('not a YouTube link')).toBeTruthy()
    expect(field().value).toBe(`${list[0]}\nnonsense`)            // nothing was added: the text stays for editing
  })

  it('the report names every link with its own reason, in the order sent, and a processed one opens its result', async () => {
    const report = [
      { url: list[0], video_id: 'listVideo001', status: 'added' },
      { url: list[1], video_id: 'listVideo002', status: 'processed' },
      { url: 'nonsense', video_id: null, status: 'invalid' },
      { url: list[0], video_id: 'listVideo001', status: 'in_list' },
      { url: list[2], video_id: 'listVideo003', status: 'in_queue' },
    ]
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 1, ids: [9], invalid: ['nonsense'], duplicates: [list[1], list[0], list[2]], report,
    } as never)
    renderHome()
    fireEvent.change(field(), { target: { value: report.map(r => r.url).join('\n') } })
    fireEvent.click(screen.getByRole('button', { name: 'Add all (5)' }))
    const box = await screen.findByTestId('bulk-report')
    expect(box.textContent).toContain('Added 1 to the queue, skipped 4.')
    const rows = Array.from(box.querySelectorAll('li'))
    expect(rows.map(r => r.getAttribute('data-status'))).toEqual(['added', 'processed', 'invalid', 'in_list', 'in_queue'])
    expect(rows.map(r => r.textContent)).toEqual([
      `check${list[0]}added to the queue`,
      `remove${list[1]}already processedOpen the result →`,
      'removenonsensenot a YouTube link',
      `remove${list[0]}duplicate in the list`,
      `remove${list[2]}already in the queue`,
    ])
    expect(screen.getByRole('link', { name: /Open the result/ }).getAttribute('href')).toBe('/result/listVideo002')
    expect(screen.getByRole('link', { name: /View queue/ }).getAttribute('href')).toBe('/queue')
  })

  it('an http:// link says that only https links are accepted, not "not a YouTube link"', async () => {
    const http = 'http://www.youtube.com/watch?v=listVideo002'
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 1, ids: [1], invalid: [http, 'nonsense'], duplicates: [],
      report: [
        { url: list[0], video_id: 'listVideo001', status: 'added' },
        { url: http, video_id: null, status: 'invalid', reason: 'http_only' },
        { url: 'nonsense', video_id: null, status: 'invalid', reason: 'not_youtube' },
      ],
    } as never)
    renderHome()
    fireEvent.change(field(), { target: { value: `${list[0]}\n${http}\nnonsense` } })
    fireEvent.click(screen.getByRole('button', { name: 'Add all (3)' }))
    const box = await screen.findByTestId('bulk-report')
    const rows = Array.from(box.querySelectorAll('li')).map(r => r.textContent)
    expect(rows[1]).toBe(`remove${http}only https links are accepted`)
    expect(rows[2]).toBe('removenonsensenot a YouTube link')
  })

  it('a list where every link is refused (400) shows each link with its reason and keeps the text', async () => {
    const http = 'http://www.youtube.com/watch?v=listVideo002'
    vi.mocked(api.queueBulkAdd).mockRejectedValue(new api.InvalidLinkError(['nonsense', http], [
      { url: 'nonsense', video_id: null, status: 'invalid', reason: 'not_youtube' },
      { url: http, video_id: null, status: 'invalid', reason: 'http_only' },
    ]))
    renderHome()
    fireEvent.change(field(), { target: { value: `nonsense\n${http}` } })
    fireEvent.click(screen.getByRole('button', { name: 'Add all (2)' }))
    const box = await screen.findByTestId('bulk-report')
    expect(box.textContent).toContain('Nothing was added, skipped 2.')
    expect(Array.from(box.querySelectorAll('li')).map(r => r.textContent)).toEqual([
      'removenonsensenot a YouTube link', `remove${http}only https links are accepted`])
    expect(screen.queryByRole('alert')).toBeNull()               // not only the generic error
    expect(field().value).toBe(`nonsense\n${http}`)
  })

  it('one refused link: the line says why (https only / not a YouTube link) and the text stays', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(new api.InvalidLinkError(['http://youtu.be/a'], [
      { url: 'http://youtu.be/a', video_id: null, status: 'invalid', reason: 'http_only' }]))
    renderHome()
    fireEvent.change(field(), { target: { value: 'http://youtu.be/a' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add to queue' }))
    expect(await screen.findByText('Only https links are accepted.')).toBeTruthy()
    expect(field().value).toBe('http://youtu.be/a')
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(new api.InvalidLinkError(['x'], [
      { url: 'x', video_id: null, status: 'invalid', reason: 'not_youtube' }]))
    fireEvent.change(field(), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add to queue' }))
    expect(await screen.findByText('Not a YouTube link.')).toBeTruthy()
  })

  it('fifty links are all in the report, in order', async () => {
    const fifty = Array.from({ length: 50 }, (_, n) => `https://youtu.be/bulk${String(n).padStart(7, '0')}`)
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 50, ids: fifty.map((_, n) => n + 1), invalid: [], duplicates: [],
      report: fifty.map((url, n) => ({ url, video_id: `bulk${String(n).padStart(7, '0')}`, status: 'added' })),
    } as never)
    renderHome()
    fireEvent.change(field(), { target: { value: fifty.join('\n') } })
    fireEvent.click(screen.getByRole('button', { name: 'Add all (50)' }))
    const box = await screen.findByTestId('bulk-report')
    expect(vi.mocked(api.queueBulkAdd).mock.calls[0][0]).toEqual(fifty)
    expect(Array.from(box.querySelectorAll('li')).map(r => r.querySelector('span.font-mono')!.textContent)).toEqual(fifty)
    expect(box.textContent).toContain('Added 50 to the queue.')
  })

  it('an answer without a report (older server) still lists the skipped links with their reason', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({
      added: 1, ids: [1], invalid: ['nonsense'], duplicates: [list[1]],
      duplicate_details: [{ url: list[1], video_id: 'listVideo002', reason: 'in_queue' }],
    })
    renderHome()
    fireEvent.change(field(), { target: { value: `${list[0]}\n${list[1]}\nnonsense` } })
    fireEvent.click(screen.getByRole('button', { name: 'Add all (3)' }))
    const box = await screen.findByTestId('bulk-report')
    expect(box.textContent).toContain('skipped 2')
    expect(box.textContent).toContain('already in the queue')
    expect(box.textContent).toContain('not a YouTube link')
  })

  it('Enter adds a single link; with several lines Enter is a new line and Ctrl+Enter adds the list', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [1], invalid: [], duplicates: [] })
    renderHome()
    fireEvent.change(field(), { target: { value: list[0] } })
    fireEvent.keyDown(field(), { key: 'Enter' })
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.queueBulkAdd).mock.calls[0][0]).toEqual([list[0]])

    fireEvent.change(field(), { target: { value: `${list[0]}\n${list[1]}` } })
    fireEvent.keyDown(field(), { key: 'Enter' })                  // plain Enter: a new line, nothing is sent
    await new Promise(r => setTimeout(r, 20))
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(field(), { key: 'Enter', ctrlKey: true })
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalledTimes(2))
    expect(vi.mocked(api.queueBulkAdd).mock.calls[1][0]).toEqual([list[0], list[1]])
  })

  it('a link pasted while the request is running is not lost when it succeeds', async () => {
    let answer!: (v: never) => void
    vi.mocked(api.queueBulkAdd).mockReturnValue(new Promise(res => { answer = res }) as never)
    renderHome()
    fireEvent.change(field(), { target: { value: list[0] } })
    fireEvent.click(screen.getByRole('button', { name: 'Add to queue' }))
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalledTimes(1))
    fireEvent.change(field(), { target: { value: `${list[0]}\n${list[1]}` } })      // pasted while "Adding..."
    answer({ added: 1, ids: [1], invalid: [], duplicates: [] } as never)
    expect(await screen.findByText(/Added to the queue/)).toBeTruthy()
    expect(field().value).toBe(list[1])                                               // only the sent line is gone
  })

  it('a list pasted over while its request runs keeps the new lines and drops the sent ones', async () => {
    let answer!: (v: never) => void
    vi.mocked(api.queueBulkAdd).mockReturnValue(new Promise(res => { answer = res }) as never)
    renderHome()
    fireEvent.change(field(), { target: { value: `${list[0]}\n${list[1]}` } })
    fireEvent.click(screen.getByRole('button', { name: 'Add all (2)' }))
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalledTimes(1))
    fireEvent.change(field(), { target: { value: `${list[0]}\n${list[1]}\n${list[2]}` } })
    answer({ added: 2, ids: [1, 2], invalid: [], duplicates: [] } as never)
    await screen.findByTestId('bulk-report')
    expect(field().value).toBe(list[2])
  })

  it('Download is a stage of the queue item: it is added last, for every pipeline, and nothing is kept in the browser', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [1], invalid: [], duplicates: [] })
    localStorage.removeItem('yt_autoDownload')
    renderHome()
    fireEvent.click(screen.getByLabelText(/^Download/))
    fireEvent.change(field(), { target: { value: list[0] } })
    fireEvent.click(screen.getByRole('button', { name: 'Add to queue' }))
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.queueBulkAdd).mock.calls[0][1]).toEqual(['extract', 'download'])
    expect(localStorage.getItem('yt_autoDownload')).toBeNull()              // the old intent that downloaded whatever video opened first
    fireEvent.change(screen.getByLabelText('Pipeline'), { target: { value: 'full' } })
    fireEvent.change(field(), { target: { value: `${list[0]}
${list[1]}` } })
    fireEvent.click(screen.getByRole('button', { name: 'Add all (2)' }))
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalledTimes(2))
    expect(vi.mocked(api.queueBulkAdd).mock.calls[1][1]).toEqual(['extract', 'cleanup', 'summary', 'mindmap', 'download'])
  })

  it('without the Download box the stages have no download, and there are no format / quality fields (Settings decides)', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [1], invalid: [], duplicates: [] })
    localStorage.removeItem('yt_autoDownload_enabled')
    renderHome()
    expect(screen.queryByText('Video (MP4)')).toBeNull()
    fireEvent.click(screen.getByLabelText(/^Download/))
    expect(screen.queryByText('Video (MP4)')).toBeNull()                    // ticking it adds no selects either
    expect(screen.getByText(/format and quality: Settings/)).toBeTruthy()
    fireEvent.click(screen.getByLabelText(/^Download/))
    fireEvent.change(field(), { target: { value: list[0] } })
    fireEvent.click(screen.getByRole('button', { name: 'Add to queue' }))
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalled())
    expect(vi.mocked(api.queueBulkAdd).mock.calls[0][1]).toEqual(['extract'])
  })

  describe('Download for a video that is already processed (review)', () => {
    const processedAnswer = {
      added: 0, ids: [], invalid: [], duplicates: [list[0]],
      duplicate_details: [{ url: list[0], video_id: 'listVideo001', reason: 'processed' }],
      report: [{ url: list[0], video_id: 'listVideo001', status: 'processed' }],
    }

    beforeEach(() => { localStorage.removeItem('yt_autoDownload_enabled') })

    it('the download is queued by itself, by id, and the line says so', async () => {
      vi.mocked(api.queueBulkAdd).mockResolvedValue(processedAnswer as never)
      vi.mocked(api.queueBulkAddByIds).mockResolvedValue({ added: 1, ids: [9], invalid: [], duplicates: [], missing: [] })
      renderHome()
      fireEvent.click(screen.getByLabelText(/^Download/))
      fireEvent.change(field(), { target: { value: list[0] } })
      fireEvent.click(screen.getByRole('button', { name: 'Add to queue' }))
      expect(await screen.findByText(/Already processed\. Download queued\./)).toBeTruthy()
      expect(api.queueBulkAddByIds).toHaveBeenCalledWith(['listVideo001'], ['download'])
      expect(screen.getByRole('link', { name: /Open the result/ }).getAttribute('href')).toBe('/result/listVideo001')
    })

    it('without the Download box nothing is queued for a processed video', async () => {
      vi.mocked(api.queueBulkAdd).mockResolvedValue(processedAnswer as never)
      renderHome()
      fireEvent.change(field(), { target: { value: list[0] } })
      fireEvent.click(screen.getByRole('button', { name: 'Add to queue' }))
      expect(await screen.findByText(/Already processed/)).toBeTruthy()
      expect(api.queueBulkAddByIds).not.toHaveBeenCalled()
    })

    it('a download that is already queued says so, and a refusal says it could not be queued', async () => {
      vi.mocked(api.queueBulkAdd).mockResolvedValue(processedAnswer as never)
      vi.mocked(api.queueBulkAddByIds).mockResolvedValueOnce({ added: 0, ids: [], invalid: [], duplicates: ['listVideo001'], missing: [] })
      renderHome()
      fireEvent.click(screen.getByLabelText(/^Download/))
      fireEvent.change(field(), { target: { value: list[0] } })
      fireEvent.click(screen.getByRole('button', { name: 'Add to queue' }))
      expect(await screen.findByText(/Download already queued\./)).toBeTruthy()
      vi.mocked(api.queueBulkAddByIds).mockRejectedValueOnce(new Error('boom'))
      fireEvent.click(screen.getByRole('button', { name: 'Add to queue' }))
      expect(await screen.findByText(/The download could not be queued\./)).toBeTruthy()
    })

    it('in a list the processed row says "download queued"; other rows and videos that are only queued get no download', async () => {
      vi.mocked(api.queueBulkAdd).mockResolvedValue({
        added: 1, ids: [3], invalid: [], duplicates: [list[0], list[2]],
        report: [
          { url: list[0], video_id: 'listVideo001', status: 'processed' },
          { url: list[1], video_id: 'listVideo002', status: 'added' },
          { url: list[2], video_id: 'listVideo003', status: 'in_queue' },
        ],
      } as never)
      vi.mocked(api.queueBulkAddByIds).mockResolvedValue({ added: 1, ids: [9], invalid: [], duplicates: [], missing: [] })
      renderHome()
      fireEvent.click(screen.getByLabelText(/^Download/))
      fireEvent.change(field(), { target: { value: list.join('\n') } })
      fireEvent.click(screen.getByRole('button', { name: 'Add all (3)' }))
      const box = await screen.findByTestId('bulk-report')
      const rows = Array.from(box.querySelectorAll('li')).map(r => r.textContent)
      expect(rows[0]).toContain('· download queued')
      expect(rows[1]).not.toContain('download queued')
      expect(rows[2]).not.toContain('download queued')
      expect(api.queueBulkAddByIds).toHaveBeenCalledWith(['listVideo001'], ['download'])      // only the processed video
    })
  })

  it('an empty field cannot be sent', () => {
    renderHome()
    expect((screen.getByRole('button', { name: 'Add to queue' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(field(), { target: { value: '  \n \n' } })
    expect((screen.getByRole('button', { name: 'Add to queue' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
