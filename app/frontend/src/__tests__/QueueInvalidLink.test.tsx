// The queue page against the REAL api module: only fetch is stubbed, with the answers the real server gives.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as unknown as Response
}

const SERVER_400 = { detail: { message: 'No valid YouTube URLs', invalid: ['not a link at all'] } }  // routers/process.py

function stubServer(bulk: () => Response) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/queue' && !init?.method) return Promise.resolve(json({ items: [], count: 0 }))
    if (url === '/api/queue/bulk') return Promise.resolve(bulk())
    return Promise.resolve(json({}, 404))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function submit(link: string) {
  fireEvent.click(await screen.findByRole('button', { name: /New/ }))
  const input = screen.getByLabelText('New video link') as HTMLInputElement
  fireEvent.change(input, { target: { value: link } })
  fireEvent.submit(input.closest('form')!)
  return input
}

describe('a link that is not a YouTube link, with the server\'s real answer (400)', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('says so, shows no failed row and no Retry, and puts the text back into the empty field', async () => {
    const fetchMock = stubServer(() => json(SERVER_400, 400))
    render(<MemoryRouter><QueuePage /></MemoryRouter>)
    const input = await submit('not a link at all')
    expect(await screen.findByText('Not a YouTube link.')).toBeTruthy()
    await waitFor(() => expect(input.value).toBe('not a link at all'))   // back for editing
    expect(screen.queryByTestId('adding-row')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    const bulkCalls = fetchMock.mock.calls.filter(c => c[0] === '/api/queue/bulk')
    expect(bulkCalls).toHaveLength(1)
  })

  it('does not overwrite what was typed in the meantime', async () => {
    stubServer(() => json(SERVER_400, 400))
    render(<MemoryRouter><QueuePage /></MemoryRouter>)
    const input = await submit('typo link')
    fireEvent.change(input, { target: { value: 'https://youtu.be/nextOne0001' } })   // typed before the answer is handled
    expect(await screen.findByText('Not a YouTube link.')).toBeTruthy()
    expect(input.value).toBe('https://youtu.be/nextOne0001')
  })

  it('a real failure (500) still shows a row with the reason and a Retry', async () => {
    stubServer(() => json({ detail: 'Internal Server Error' }, 500))
    render(<MemoryRouter><QueuePage /></MemoryRouter>)
    await submit('https://youtu.be/serverBroke1')
    expect(await screen.findByText('Not added: Internal Server Error')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })
})
