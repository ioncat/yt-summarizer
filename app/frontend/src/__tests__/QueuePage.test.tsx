import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import * as api from '../api'

vi.mock('../api', () => ({
  getQueue: vi.fn(),
  queueBulkAdd: vi.fn(),
  deleteQueueItem: vi.fn(),
  clearQueuePending: vi.fn(),
  clearQueueFailed: vi.fn(),
  retryQueueItem: vi.fn(),
  retryAllFailed: vi.fn(),
}))

const item = (id: number, url: string, extra = {}): api.QueueItem => ({
  id, url, video_id: null, db_video_id: null, status: 'pending', pipeline_stages: ['extract'],
  error_message: null, added_at: '2026-11-05T10:00:00', started_at: null, finished_at: null,
  sort_order: id, progress: null, ...extra,
} as api.QueueItem)

function Where() { return <div data-testid="where">{useLocation().pathname}</div> }

function renderQueue() {
  return render(
    <MemoryRouter initialEntries={['/queue']}>
      <Routes><Route path="*" element={<><QueuePage /><Where /></>} /></Routes>
    </MemoryRouter>
  )
}

async function openAndSubmit(link: string) {
  fireEvent.click(await screen.findByRole('button', { name: /New/ }))
  const input = screen.getByLabelText('New video link')
  fireEvent.change(input, { target: { value: link } })
  fireEvent.submit(input.closest('form')!)
}

describe('QueuePage "New" (NS-24a)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getQueue).mockResolvedValue({ items: [], count: 0 })
  })

  it('adds one link with the default pipeline, stays on the page, clears the field and reloads the table', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [9], invalid: [], duplicates: [], duplicate_details: [] })
    renderQueue()
    await openAndSubmit('https://youtu.be/newVideo001')
    expect(await screen.findByText('Added to the queue.')).toBeTruthy()
    // explicit stages, the Home page's default (extract only); not forced
    expect(api.queueBulkAdd).toHaveBeenCalledWith(['https://youtu.be/newVideo001'], ['extract'], false)
    expect((screen.getByLabelText('New video link') as HTMLInputElement).value).toBe('')
    expect(screen.getByTestId('where').textContent).toBe('/queue')
    vi.mocked(api.getQueue).mockResolvedValue({ items: [item(9, 'https://youtu.be/newVideo001')], count: 1 })
    await waitFor(() => expect(vi.mocked(api.getQueue).mock.calls.length).toBeGreaterThan(1))  // reloaded after the add
  })

  it('uses the full pipeline when the Home page checkbox "Run full pipeline" is on', async () => {
    localStorage.setItem('yt_summarizer_auto_pipeline', 'true')
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [1], invalid: [], duplicates: [] })
    renderQueue()
    await openAndSubmit('https://youtu.be/newVideo001')
    await screen.findByText('Added to the queue.')
    expect(api.queueBulkAdd).toHaveBeenCalledWith(
      ['https://youtu.be/newVideo001'], ['extract', 'cleanup', 'summary', 'mindmap'], false)
    localStorage.removeItem('yt_summarizer_auto_pipeline')
  })

  it('a second link can be added right after the first', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [1], invalid: [], duplicates: [] })
    renderQueue()
    await openAndSubmit('https://youtu.be/firstVideo01')
    await screen.findByText('Added to the queue.')
    fireEvent.change(screen.getByLabelText('New video link'), { target: { value: 'https://youtu.be/secondVideo1' } })
    fireEvent.submit(screen.getByLabelText('New video link').closest('form')!)
    await waitFor(() => expect(api.queueBulkAdd).toHaveBeenCalledTimes(2))
  })

  it('says why a link was not added: processed (with a link to the result), already queued, not a YouTube link', async () => {
    renderQueue()
    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({
      added: 0, ids: [], invalid: [], duplicates: ['https://www.youtube.com/live/Ifr9JgTm2TE'],
      duplicate_details: [{ url: 'https://www.youtube.com/live/Ifr9JgTm2TE', video_id: 'Ifr9JgTm2TE', reason: 'processed' }],
    })
    await openAndSubmit('https://www.youtube.com/live/Ifr9JgTm2TE')
    const open = await screen.findByRole('link', { name: 'Open the result' })
    expect(open.getAttribute('href')).toBe('/result/Ifr9JgTm2TE')
    expect(screen.getByTestId('where').textContent).toBe('/queue')

    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({
      added: 0, ids: [], invalid: [], duplicates: ['x'],
      duplicate_details: [{ url: 'x', video_id: 'v', reason: 'in_queue' }],
    })
    fireEvent.submit(screen.getByLabelText('New video link').closest('form')!)
    expect(await screen.findByText('Already in the queue.')).toBeTruthy()

    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({ added: 0, ids: [], invalid: ['nope'], duplicates: [] })
    fireEvent.submit(screen.getByLabelText('New video link').closest('form')!)
    expect(await screen.findByText('Not a YouTube link.')).toBeTruthy()
  })

  it('a failed add stays visible as a row with the reason and a Retry; what was typed is kept', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValue(new Error('boom'))
    renderQueue()
    await openAndSubmit('https://youtu.be/newVideo001')
    expect(await screen.findByText('Not added: boom')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
    expect((screen.getByLabelText('New video link') as HTMLInputElement).value).toBe('https://youtu.be/newVideo001')
  })

  it('shows an "Adding..." row at once, before the server has answered, and drops it when the add succeeded', async () => {
    let answer!: (v: api.QueueAddResult) => void
    vi.mocked(api.queueBulkAdd).mockReturnValue(new Promise(res => { answer = res }))
    renderQueue()
    await openAndSubmit('https://youtu.be/slowAdd0001')
    const row = await screen.findByTestId('adding-row')
    expect(row.textContent).toContain('https://youtu.be/slowAdd0001')
    expect(row.textContent).toContain('Adding…')
    expect(screen.getByRole('button', { name: 'Adding…' })).toBeTruthy()
    answer({ added: 1, ids: [1], invalid: [], duplicates: [] })
    await waitFor(() => expect(screen.queryByTestId('adding-row')).toBeNull())
    expect(await screen.findByText('Added to the queue.')).toBeTruthy()
  })

  it('Retry sends the same link again and the row goes away once it is added', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(new Error('database busy, try again'))
    renderQueue()
    await openAndSubmit('https://youtu.be/retryMe0001')
    await screen.findByText('Not added: database busy, try again')
    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({ added: 1, ids: [7], invalid: [], duplicates: [] })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.queryByTestId('adding-row')).toBeNull())
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.queueBulkAdd).mock.calls[1][0]).toEqual(['https://youtu.be/retryMe0001'])
  })

  it('pressing Enter twice for the same link sends one request, and the button is off while it runs', async () => {
    let answer!: (v: api.QueueAddResult) => void
    vi.mocked(api.queueBulkAdd).mockReturnValue(new Promise(res => { answer = res }))
    renderQueue()
    await openAndSubmit('https://youtu.be/doubleEnter1')
    const form = screen.getByLabelText('New video link').closest('form')!
    fireEvent.submit(form)                                    // a second Enter at once
    fireEvent.submit(form)                                    // and a third
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(1)
    expect(screen.getAllByTestId('adding-row')).toHaveLength(1)
    await waitFor(() => expect((screen.getByRole('button', { name: 'Adding…' }) as HTMLButtonElement).disabled).toBe(true))
    answer({ added: 1, ids: [1], invalid: [], duplicates: [] })
    await waitFor(() => expect(screen.queryByTestId('adding-row')).toBeNull())
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(1)
  })

  it('another link can be added while the first is still being sent', async () => {
    vi.mocked(api.queueBulkAdd).mockReturnValue(new Promise(() => {}))   // never answers
    renderQueue()
    await openAndSubmit('https://youtu.be/firstLink001')
    fireEvent.change(screen.getByLabelText('New video link'), { target: { value: 'https://youtu.be/secondLink01' } })
    expect((screen.getByRole('button', { name: 'Adding…' }) as HTMLButtonElement).disabled).toBe(false)
    fireEvent.submit(screen.getByLabelText('New video link').closest('form')!)
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(2)
    expect(screen.getAllByTestId('adding-row')).toHaveLength(2)
  })

  it('clicking Retry twice sends the link once', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(new Error('boom'))
    renderQueue()
    await openAndSubmit('https://youtu.be/retryTwice01')
    await screen.findByText('Not added: boom')
    vi.mocked(api.queueBulkAdd).mockReturnValueOnce(new Promise(() => {}))
    const retry = screen.getByRole('button', { name: 'Retry' })
    fireEvent.click(retry)
    fireEvent.click(retry)
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(2)         // the first try + ONE retry
  })

  it('Dismiss removes a failed row without sending anything', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValue(new Error('boom'))
    renderQueue()
    await openAndSubmit('https://youtu.be/dismissMe01')
    await screen.findByText('Not added: boom')
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByTestId('adding-row')).toBeNull()
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(1)
  })

  it('an empty field adds nothing and Close hides the form', async () => {
    renderQueue()
    fireEvent.click(await screen.findByRole('button', { name: /New/ }))
    fireEvent.submit(screen.getByLabelText('New video link').closest('form')!)
    expect(api.queueBulkAdd).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByLabelText('New video link')).toBeNull()
  })

  it('shows a local file by its name (not blank)', async () => {
    vi.mocked(api.getQueue).mockResolvedValue({ items: [item(3, 'local://talk.m4a', { video_id: 'file-1a2b3c4d' })], count: 1 })
    renderQueue()
    expect(await screen.findByText('talk.m4a')).toBeTruthy()
  })
})


describe('QueuePage polling (NS-28)', () => {
  beforeEach(() => { vi.clearAllMocks() })
  afterEach(() => { vi.useRealTimers() })

  it('keeps one poll in flight: a slow answer is not overtaken by new requests', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let answer!: (v: { items: api.QueueItem[]; count: number }) => void
    vi.mocked(api.getQueue).mockReturnValue(new Promise(res => { answer = res }))
    renderQueue()
    await vi.advanceTimersByTimeAsync(10_000)               // three poll ticks while the first is still unanswered
    expect(api.getQueue).toHaveBeenCalledTimes(1)
    vi.mocked(api.getQueue).mockResolvedValue({ items: [], count: 0 })
    answer({ items: [], count: 0 })
    await vi.advanceTimersByTimeAsync(3_100)
    expect(vi.mocked(api.getQueue).mock.calls.length).toBeGreaterThanOrEqual(2)  // polling goes on afterwards
  })

  it('an add that finishes during a poll triggers one more load whose answer wins', async () => {
    let first!: (v: { items: api.QueueItem[]; count: number }) => void
    vi.mocked(api.getQueue).mockReturnValueOnce(new Promise(res => { first = res }))  // the initial load, slow
    vi.mocked(api.getQueue).mockResolvedValue({ items: [item(9, 'https://youtu.be/justAdded001')], count: 1 })
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [9], invalid: [], duplicates: [] })
    renderQueue()
    await openAndSubmit('https://youtu.be/justAdded001')
    await screen.findByText('Added to the queue.')
    expect(api.getQueue).toHaveBeenCalledTimes(1)             // the reload waits for the poll in flight
    first({ items: [], count: 0 })                            // the OLD answer (no row) arrives first
    await waitFor(() => expect(api.getQueue).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('justAdded001')).toBeTruthy()  // the newer answer is what stays
  })

  it('after two failed polls a banner says the backend cannot be reached, the old list stays, and it clears on success', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(api.getQueue).mockResolvedValueOnce({ items: [item(1, 'https://youtu.be/lastGood0001')], count: 1 })
    vi.mocked(api.getQueue).mockRejectedValue(new Error('Cannot reach the server. Is the backend running?'))
    renderQueue()
    await vi.advanceTimersByTimeAsync(100)
    expect(await screen.findByText('lastGood0001')).toBeTruthy()
    await vi.advanceTimersByTimeAsync(3_100)                   // 1st failed poll: no banner yet
    expect(screen.queryByRole('alert')).toBeNull()
    await vi.advanceTimersByTimeAsync(3_100)                   // 2nd failed poll
    expect((await screen.findByRole('alert')).textContent).toContain('Cannot reach the backend')
    expect(screen.getByText('lastGood0001')).toBeTruthy()   // last good list still shown
    vi.mocked(api.getQueue).mockResolvedValue({ items: [item(1, 'https://youtu.be/lastGood0001')], count: 1 })
    await vi.advanceTimersByTimeAsync(3_100)
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  })
})
