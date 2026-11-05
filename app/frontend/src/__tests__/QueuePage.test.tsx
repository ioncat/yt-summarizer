import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import * as api from '../api'

vi.mock('../api', () => ({
  UncertainAddError: class UncertainAddError extends Error {},
  InvalidLinkError: class InvalidLinkError extends Error {
    constructor(public invalid: string[] = []) { super('No valid YouTube URLs') }
  },
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
    fireEvent.change(screen.getByLabelText('New video link'), { target: { value: 'https://youtu.be/alreadyQueued' } })
    fireEvent.submit(screen.getByLabelText('New video link').closest('form')!)
    expect(await screen.findByText('Already in the queue.')).toBeTruthy()

    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({ added: 0, ids: [], invalid: ['nope'], duplicates: [] })
    fireEvent.change(screen.getByLabelText('New video link'), { target: { value: 'not a link' } })
    fireEvent.submit(screen.getByLabelText('New video link').closest('form')!)
    expect(await screen.findByText('Not a YouTube link.')).toBeTruthy()
  })

  it('a failed add stays visible as a row with the reason and a Retry; the link lives in that row, the field is free', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValue(new Error('boom'))
    renderQueue()
    await openAndSubmit('https://youtu.be/newVideo001')
    expect(await screen.findByText('Not added: boom')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
    expect(screen.getByTestId('adding-row').textContent).toContain('newVideo001')
    expect((screen.getByLabelText('New video link') as HTMLInputElement).value).toBe('')
  })

  it('five links submitted in quick succession are all sent, none lost, whatever order the answers come in', async () => {
    const answers: Array<(v: api.QueueAddResult) => void> = []
    vi.mocked(api.queueBulkAdd).mockImplementation(() => new Promise(res => { answers.push(res) }))
    renderQueue()
    fireEvent.click(await screen.findByRole('button', { name: /New/ }))
    const input = screen.getByLabelText('New video link') as HTMLInputElement
    const links = [1, 2, 3, 4, 5].map(i => `https://youtu.be/rapidLink0${i}`)
    for (const link of links) {                               // type + Enter, one after the other, nothing awaited
      fireEvent.change(input, { target: { value: link } })
      fireEvent.submit(input.closest('form')!)
      expect(input.value).toBe('')                            // the field is free again at once
    }
    expect(vi.mocked(api.queueBulkAdd).mock.calls.map(c => c[0][0])).toEqual(links)
    expect(screen.getAllByTestId('adding-row')).toHaveLength(5)
    for (const i of [2, 0, 4, 1, 3]) answers[i]({ added: 1, ids: [i], invalid: [], duplicates: [] })  // answers out of order
    await waitFor(() => expect(screen.queryAllByTestId('adding-row')).toHaveLength(0))
    expect(input.value).toBe('')
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(5)
  })

  it('what is typed while the previous link is still being added is not wiped when that request finishes', async () => {
    let answerFirst!: (v: api.QueueAddResult) => void
    vi.mocked(api.queueBulkAdd).mockReturnValueOnce(new Promise(res => { answerFirst = res }))
    vi.mocked(api.queueBulkAdd).mockReturnValue(new Promise(() => {}))
    renderQueue()
    await openAndSubmit('https://youtu.be/firstTyped01')
    const input = screen.getByLabelText('New video link') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'https://youtu.be/typedAfter01' } })   // ~20 ms after Enter
    answerFirst({ added: 1, ids: [1], invalid: [], duplicates: [] })
    await screen.findByText('Added to the queue.')
    expect(input.value).toBe('https://youtu.be/typedAfter01')   // still there
    fireEvent.submit(input.closest('form')!)
    expect(vi.mocked(api.queueBulkAdd).mock.calls[1][0]).toEqual(['https://youtu.be/typedAfter01'])  // and it is sent, not an empty box
  })

  it('a link the server calls invalid comes back to the field for editing, unless something else was typed', async () => {
    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({ added: 0, ids: [], invalid: ['nope'], duplicates: [] })
    renderQueue()
    await openAndSubmit('htp://typo.example/watch?v=1')
    expect(await screen.findByText('Not a YouTube link.')).toBeTruthy()
    await waitFor(() => expect((screen.getByLabelText('New video link') as HTMLInputElement).value).toBe('htp://typo.example/watch?v=1'))
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

  it('no answer to an add: the row says the link may have been added, it does not claim "Not added"', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValue(
      new api.UncertainAddError('No answer from the server. The link may have been added: check the queue before retrying.'))
    renderQueue()
    await openAndSubmit('https://youtu.be/lostAnswer01')
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toBe('No answer from the server. The link may have been added: check the queue before retrying.')
    expect(alert.textContent).not.toContain('Not added')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })

  it('Retry after a lost answer finds the link already queued: "Already in the queue." shows, the row goes, the field is clear', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(
      new api.UncertainAddError('No answer from the server. The link may have been added: check the queue before retrying.'))
    renderQueue()
    await openAndSubmit('https://youtu.be/lostAnswer02')
    await screen.findByRole('alert')
    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({
      added: 0, ids: [], invalid: [], duplicates: ['https://youtu.be/lostAnswer02'],
      duplicate_details: [{ url: 'https://youtu.be/lostAnswer02', video_id: 'lostAnswer02', reason: 'in_queue' }],
    })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Already in the queue.')).toBeTruthy()
    expect(screen.queryByTestId('adding-row')).toBeNull()                 // one row all along, now gone
    expect((screen.getByLabelText('New video link') as HTMLInputElement).value).toBe('')
    expect(api.queueBulkAdd).toHaveBeenCalledTimes(2)
  })

  it('Retry creates no second row while it runs', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(new Error('boom'))
    renderQueue()
    await openAndSubmit('https://youtu.be/oneRowOnly01')
    await screen.findByText('Not added: boom')
    vi.mocked(api.queueBulkAdd).mockReturnValueOnce(new Promise(() => {}))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(screen.getAllByTestId('adding-row')).toHaveLength(1)
    expect(screen.getByTestId('adding-row').textContent).toContain('Adding…')
  })

  it('the same link typed again into the field is cleared once its Retry settles as already queued', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValueOnce(new Error('boom'))
    renderQueue()
    await openAndSubmit('https://youtu.be/typedAgain001')
    await screen.findByText('Not added: boom')
    fireEvent.change(screen.getByLabelText('New video link'), { target: { value: 'https://youtu.be/typedAgain001' } })
    vi.mocked(api.queueBulkAdd).mockResolvedValueOnce({
      added: 0, ids: [], invalid: [], duplicates: ['x'],
      duplicate_details: [{ url: 'x', video_id: 'typedAgain001', reason: 'in_queue' }],
    })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('Already in the queue.')
    await waitFor(() => expect((screen.getByLabelText('New video link') as HTMLInputElement).value).toBe(''))
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

  it('leaving the page while a reload is waiting for the poll in flight starts no further load', async () => {
    let first!: (v: { items: api.QueueItem[]; count: number }) => void
    vi.mocked(api.getQueue).mockReturnValueOnce(new Promise(res => { first = res }))
    vi.mocked(api.getQueue).mockResolvedValue({ items: [], count: 0 })
    vi.mocked(api.queueBulkAdd).mockResolvedValue({ added: 1, ids: [9], invalid: [], duplicates: [] })
    const view = renderQueue()
    await openAndSubmit('https://youtu.be/leavePage001')
    await screen.findByText('Added to the queue.')            // a reload is now waiting behind the first poll
    expect(api.getQueue).toHaveBeenCalledTimes(1)
    view.unmount()
    first({ items: [], count: 0 })
    await new Promise(r => setTimeout(r, 50))
    expect(api.getQueue).toHaveBeenCalledTimes(1)             // no stray second load after the page is gone
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

describe('QueuePage "partial" items (NS-25)', () => {
  const partial = item(5, 'https://youtu.be/partial0001', {
    status: 'partial', pipeline_stages: ['cleanup', 'summary'], error_message: 'Summary failed: the model returned nothing',
  })
  const failed = item(6, 'https://youtu.be/failed00001', { status: 'failed', error_message: 'boom' })

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getQueue).mockResolvedValue({ items: [partial, failed], count: 2 })
  })

  it('shows a "partial" pill whose message names the failed stage', async () => {
    renderQueue()
    expect(await screen.findByText('partial')).toBeTruthy()
    fireEvent.click(screen.getAllByText('expand_more')[0])
    expect(screen.getByText('Summary failed: the model returned nothing')).toBeTruthy()
  })

  it('"Retry failed" counts partial items, "Clean failed" counts only the failed ones', async () => {
    renderQueue()
    expect(await screen.findByRole('button', { name: /Retry failed \(2\)/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Clean failed \(1\)/ })).toBeTruthy()
  })

  it('a partial item has its own Retry, which reloads the table (it now holds only its failed stages)', async () => {
    vi.mocked(api.retryQueueItem).mockResolvedValue({ retried: 5 } as never)
    renderQueue()
    await screen.findByText('partial')
    fireEvent.click(screen.getAllByTitle('Retry the failed stages')[0])
    await waitFor(() => expect(api.retryQueueItem).toHaveBeenCalledWith(5))
    await waitFor(() => expect(vi.mocked(api.getQueue).mock.calls.length).toBeGreaterThan(1))
  })

  it('Clean failed removes failed rows but keeps the partial one', async () => {
    vi.mocked(api.clearQueueFailed).mockResolvedValue({ cleared: 1 } as never)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderQueue()
    fireEvent.click(await screen.findByRole('button', { name: /Clean failed/ }))
    await waitFor(() => expect(screen.queryByText('boom')).toBeNull())
    expect(screen.getByText('partial')).toBeTruthy()
  })
})
