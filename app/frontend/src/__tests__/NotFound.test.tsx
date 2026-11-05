import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import * as api from '../api'

vi.mock('../api', async importOriginal => ({
  ...(await importOriginal<typeof import('../api')>()),
  getHealth: vi.fn().mockResolvedValue({ backend: true, ollama: false }),
  getQueueCounts: vi.fn().mockResolvedValue({ pending: 0, processing: 0, active: 0 }),
  getResult: vi.fn(),
}))

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
}

describe('unknown addresses and videos (NS-24a)', () => {
  it('/result/<a whole url> shows Not found, not a blank page', async () => {
    renderAt('/result/https:/www.youtube.com/live/Ifr9JgTm2TE')
    expect(await screen.findByTestId('not-found')).toBeTruthy()
    expect(screen.getByText(/Nothing is here/)).toBeTruthy()
    expect(screen.getByText('/result/https:/www.youtube.com/live/Ifr9JgTm2TE')).toBeTruthy()
  })

  it('an unknown page address shows Not found', async () => {
    renderAt('/no-such-page')
    expect(await screen.findByTestId('not-found')).toBeTruthy()
  })

  it('a video id that is not in History says so (the backend answered 404)', async () => {
    vi.mocked(api.getResult).mockRejectedValue(new Error('Result not found'))
    renderAt('/result/nope1234567')
    expect(await screen.findByText('Video "nope1234567" was not found in History.')).toBeTruthy()
  })

  it('any other load failure keeps the generic message', async () => {
    vi.mocked(api.getResult).mockRejectedValue(new Error('Failed to load result'))
    renderAt('/result/abc1234567x')
    await waitFor(() => expect(screen.getByText('Could not load result')).toBeTruthy())
  })

  it('the existing pages are still reachable', async () => {
    renderAt('/queue')
    await waitFor(() => expect(screen.queryByTestId('not-found')).toBeNull())
  })
})
