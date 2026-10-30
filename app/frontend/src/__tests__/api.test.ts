import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  processVideo,
  getResult,
  getHistory,
  VideoAlreadyExistsError,
} from '../api'

function makeResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response
}

describe('api.ts', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  describe('processVideo', () => {
    it('calls /api/process with correct body', async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        makeResponse({ task_id: 'task1', video_id: 'vid1' })
      )
      vi.stubGlobal('fetch', fetchMock)

      const result = await processVideo('https://youtube.com/watch?v=abc', 'ru')

      expect(fetchMock).toHaveBeenCalledOnce()
      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toBe('/api/process')
      expect(init?.method).toBe('POST')
      const body = JSON.parse(init?.body as string)
      expect(body.url).toBe('https://youtube.com/watch?v=abc')
      expect(body.language).toBe('ru')
      expect(result.task_id).toBe('task1')
      expect(result.video_id).toBe('vid1')
    })

    it('throws VideoAlreadyExistsError on 409', async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        makeResponse({ detail: { video_id: 'existing-vid' } }, 409)
      )
      vi.stubGlobal('fetch', fetchMock)

      await expect(processVideo('https://youtube.com/watch?v=abc', 'en')).rejects.toThrow(
        VideoAlreadyExistsError
      )
    })

    it('throws generic Error on 4xx (not 409)', async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        makeResponse({ detail: 'Bad request' }, 400)
      )
      vi.stubGlobal('fetch', fetchMock)

      await expect(processVideo('not-a-url', 'en')).rejects.toThrow('Bad request')
    })
  })

  describe('getResult', () => {
    it('calls /api/result/{videoId} with correct URL', async () => {
      const mockResult = { video_id: 'vid1', formatted_text: 'hello' }
      const fetchMock = vi.fn().mockResolvedValue(makeResponse(mockResult))
      vi.stubGlobal('fetch', fetchMock)

      const result = await getResult('vid1')

      expect(fetchMock).toHaveBeenCalledOnce()
      expect(fetchMock.mock.calls[0][0]).toBe('/api/result/vid1')
      expect(result.video_id).toBe('vid1')
    })

    it('throws on non-ok response', async () => {
      const fetchMock = vi.fn().mockResolvedValue(makeResponse({}, 404))
      vi.stubGlobal('fetch', fetchMock)

      await expect(getResult('missing-id')).rejects.toThrow('Result not found')
    })
  })

  describe('getHistory', () => {
    it('calls /api/history with default page=1', async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        makeResponse({ page: 1, items: [] })
      )
      vi.stubGlobal('fetch', fetchMock)

      const result = await getHistory()

      expect(fetchMock).toHaveBeenCalledOnce()
      const url = fetchMock.mock.calls[0][0] as string
      expect(url).toContain('/api/history')
      expect(url).toContain('page=1')
      expect(result.page).toBe(1)
    })

    it('calls /api/history with specified page number', async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        makeResponse({ page: 3, items: [] })
      )
      vi.stubGlobal('fetch', fetchMock)

      await getHistory(3)

      const url = fetchMock.mock.calls[0][0] as string
      expect(url).toContain('page=3')
    })

    it('throws on non-ok response', async () => {
      const fetchMock = vi.fn().mockResolvedValue(makeResponse({}, 500))
      vi.stubGlobal('fetch', fetchMock)

      await expect(getHistory()).rejects.toThrow('Failed to load history')
    })
  })
})
