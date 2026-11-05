import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import HistoryPage from '../pages/HistoryPage'
import * as api from '../api'

vi.mock('../api', () => ({
  getHistory: vi.fn(),
  deleteResult: vi.fn(),
  deleteResultsBulk: vi.fn(),
  queueBulkAddByIds: vi.fn(),
  toggleFavorite: vi.fn(),
}))

const LOCAL_ID = 'file-8dd2037a'
const items = [
  { video_id: 'dQw4w9WgXcQ', url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', title: 'A YouTube video', author: 'Ann',
    language: 'en', char_count: 1000, created_at: '2026-11-01T10:00:00' },
  { video_id: LOCAL_ID, url: 'local://talk.m4a', title: 'talk.m4a', author: null,
    language: 'en', char_count: 800, subtitle_source: 'transcript', created_at: '2026-11-02T10:00:00' },
]

async function renderAndSelectAll() {
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  await screen.findByText('A YouTube video')
  fireEvent.click(screen.getByText('Select'))
  fireEvent.click(screen.getByText('Select all'))
}

describe('HistoryPage bulk queue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getHistory).mockResolvedValue({ page: 1, items } as never)
  })

  it('queues the selected rows by video_id, a local file keeps its full id', async () => {
    vi.mocked(api.queueBulkAddByIds).mockResolvedValue({ added: 2, ids: [1, 2], invalid: [], duplicates: [], missing: [] })
    await renderAndSelectAll()
    fireEvent.click(screen.getByText('Queue (2)'))
    await waitFor(() => expect(api.queueBulkAddByIds).toHaveBeenCalledOnce())
    const [ids, stages] = vi.mocked(api.queueBulkAddByIds).mock.calls[0]
    expect([...ids].sort()).toEqual([LOCAL_ID, 'dQw4w9WgXcQ'].sort())
    expect(stages).toEqual(['cleanup', 'summary'])
    expect(await screen.findByText(/Added 2 videos to queue/)).toBeTruthy()
  })

  it('says how many were already queued or not found', async () => {
    vi.mocked(api.queueBulkAddByIds).mockResolvedValue({ added: 1, ids: [3], invalid: [], duplicates: [LOCAL_ID], missing: ['x'] })
    await renderAndSelectAll()
    fireEvent.click(screen.getByText('Queue (2)'))
    expect(await screen.findByText(/Added 1 video to queue \(1 already in the queue\) \(1 not found\)/)).toBeTruthy()
  })

  it('shows a failure message when the request fails', async () => {
    vi.mocked(api.queueBulkAddByIds).mockRejectedValue(new Error('boom'))
    await renderAndSelectAll()
    fireEvent.click(screen.getByText('Queue (2)'))
    expect(await screen.findByText(/Failed to add to queue/)).toBeTruthy()
  })
})
