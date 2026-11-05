import { describe, it, expect, vi, beforeEach } from 'vitest'
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

  it('shows the error when the request fails and keeps what was typed', async () => {
    vi.mocked(api.queueBulkAdd).mockRejectedValue(new Error('boom'))
    renderQueue()
    await openAndSubmit('https://youtu.be/newVideo001')
    expect(await screen.findByText('boom')).toBeTruthy()
    expect((screen.getByLabelText('New video link') as HTMLInputElement).value).toBe('https://youtu.be/newVideo001')
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
