import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  processVideo,
  getResult,
  getHistory,
  VideoAlreadyExistsError,
  queueBulkAdd,
  queueBulkAddByIds,
  deleteQueueItem,
  cancelQueueItem,
  cancelVideoJobs,
  errorText,
  toggleFavorite,
  deleteResult,
  startSummary,
  startCleanup,
  startMindmap,
  getStatus,
  getQueue,
  ADD_TIMEOUT_MS,
  UncertainAddError,
  InvalidLinkError,
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


describe('error messages from the server (NS-24a review)', () => {
  const tooLong = {
    detail: [{
      type: 'too_long', loc: ['body', 'urls'], msg: 'List should have at most 500 items after validation, not 501',
      input: [], ctx: { field_type: 'List', max_length: 500, actual_length: 501 },
    }],
  }

  beforeEach(() => { vi.resetAllMocks() })

  it('a 422 "too long" list says how many items are allowed, never [object Object]', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse(tooLong, 422)))
    await expect(queueBulkAdd(['x'])).rejects.toThrow('Too many items (max 500 per request)')
    await expect(queueBulkAddByIds(['file-1'], ['cleanup'])).rejects.toThrow('Too many items (max 500 per request)')
  })

  it('any other 422 shows the first problem message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse(
      { detail: [{ type: 'missing', loc: ['body', 'url'], msg: 'Field required' }] }, 422)))
    await expect(queueBulkAdd(['x'])).rejects.toThrow('Field required')
  })

  it('string and {message} details still work, and an odd body falls back to the generic text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({ detail: { message: 'No valid YouTube URLs' } }, 400)))
    await expect(queueBulkAdd(['x'])).rejects.toThrow('No valid YouTube URLs')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({ detail: 'Cannot delete a processing item' }, 409)))
    await expect(deleteQueueItem(1)).rejects.toThrow('Cannot delete a processing item')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({ detail: 'This item is already over: nothing to cancel' }, 409)))
    await expect(cancelQueueItem(1)).rejects.toThrow('This item is already over: nothing to cancel')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({}, 500)))
    await expect(cancelQueueItem(1)).rejects.toThrow('Failed to cancel')
    await expect(cancelVideoJobs('abc123')).rejects.toThrow('Failed to stop')
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ status: 'idle', removed: 0, stopping: 0 }, 200))
    vi.stubGlobal('fetch', fetchMock)
    expect((await cancelVideoJobs('abc123')).status).toBe('idle')
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/result/abc123/cancel'), { method: 'POST' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({ detail: { weird: true } }, 500)))
    await expect(queueBulkAdd(['x'])).rejects.toThrow('Failed to add to queue')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({}, 500)))
    await expect(queueBulkAdd(['x'])).rejects.toThrow('Failed to add to queue')
  })

  it('errorText never returns an object text', () => {
    for (const body of [null, undefined, {}, { detail: [] }, { detail: [{}] }, { detail: {} }, { detail: 5 }]) {
      expect(errorText(body, 'fallback')).toBe('fallback')
    }
  })
})


describe('ids from the address bar are encoded in the request path (NS-24a review)', () => {
  const odd = 'https:/www.youtube.com/live/X?a=1#b'
  const encoded = encodeURIComponent(odd)

  beforeEach(() => { vi.resetAllMocks() })

  it('getResult keeps a slash, a ? or a # inside the id instead of changing the path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ video_id: odd }))
    vi.stubGlobal('fetch', fetchMock)
    await getResult(odd)
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/result/${encoded}`)
  })

  it('the other result calls and the status call encode the id too', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ is_favorite: true, status: 'pending' }))
    vi.stubGlobal('fetch', fetchMock)
    await toggleFavorite(odd)
    await deleteResult(odd)
    await startSummary(odd)
    await startCleanup(odd)
    await startMindmap(odd, true)
    await getStatus(odd)
    const urls = fetchMock.mock.calls.map(c => c[0] as string)
    expect(urls).toEqual([
      `/api/result/${encoded}/favorite`,
      `/api/result/${encoded}`,
      `/api/result/${encoded}/summary`,
      `/api/result/${encoded}/cleanup`,
      `/api/result/${encoded}/mindmap?force=true`,
      `/api/status/${encoded}`,
    ])
  })

  it('a normal id (YouTube or file-...) is unchanged', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({}))
    vi.stubGlobal('fetch', fetchMock)
    await getResult('dQw4w9WgXcQ')
    await getResult('file-1a2b3c4d')
    expect(fetchMock.mock.calls.map(c => c[0])).toEqual(['/api/result/dQw4w9WgXcQ', '/api/result/file-1a2b3c4d'])
  })
})


describe('add and poll calls give up instead of hanging (NS-28)', () => {
  beforeEach(() => { vi.resetAllMocks() })
  afterEach(() => { vi.useRealTimers() })

  function hangingFetch() {
    return vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_res, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('The operation was aborted.', 'AbortError')))
    }))
  }

  it('queueBulkAdd and queueBulkAddByIds fail after 40 s and tell the user the link may have been added', async () => {
    vi.useFakeTimers()
    const fetchMock = hangingFetch()
    vi.stubGlobal('fetch', fetchMock)
    const a = expect(queueBulkAdd(['x'])).rejects.toThrow(
      'No answer from the server in 40 s. The link may have been added: check the queue before retrying.')
    const b = expect(queueBulkAddByIds(['file-1'], ['cleanup'])).rejects.toThrow('No answer from the server in 40 s. The link may')
    await vi.advanceTimersByTimeAsync(39_999)
    expect(fetchMock.mock.calls.every(c => c[1]?.signal?.aborted === false)).toBe(true)  // not before 40 s
    await vi.advanceTimersByTimeAsync(2)
    await a
    await b
  })

  it('getQueue fails after 10 s, so a hung poll cannot stop the polling for good', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', hangingFetch())
    const p = expect(getQueue()).rejects.toThrow('No answer from the server in 10 s. The server may be busy or not running.')
    await vi.advanceTimersByTimeAsync(10_001)
    await p
  })

  it('a lost connection on an ADD says the link may have been added, not "backend not running"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = await queueBulkAdd(['x']).catch(e => e)
    expect(err).toBeInstanceOf(UncertainAddError)
    expect(err.message).toBe('No answer from the server. The link may have been added: check the queue before retrying.')
    await expect(queueBulkAddByIds(['file-1'], ['cleanup'])).rejects.toBeInstanceOf(UncertainAddError)
  })

  it('a timeout on an add is an UncertainAddError too; a server answer (even 503) is not', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', hangingFetch())
    const timedOut = queueBulkAdd(['x']).catch(e => e)
    await vi.advanceTimersByTimeAsync(40_001)
    expect(await timedOut).toBeInstanceOf(UncertainAddError)
    vi.useRealTimers()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({ detail: 'database busy, try again' }, 503)))
    const busy = await queueBulkAdd(['x']).catch(e => e)
    expect(busy).not.toBeInstanceOf(UncertainAddError)   // the server answered: the link was not added
    expect(busy.message).toBe('database busy, try again')
  })

  it('the real 400 for a link that is not a YouTube link is a typed InvalidLinkError (not a retryable failure)', async () => {
    const body = { detail: { message: 'No valid YouTube URLs', invalid: ['https://example.com/x'] } }  // the server's shape
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse(body, 400)))
    const err = await queueBulkAdd(['https://example.com/x']).catch(e => e)
    expect(err).toBeInstanceOf(InvalidLinkError)
    expect(err).not.toBeInstanceOf(UncertainAddError)
    expect(err.message).toBe('No valid YouTube URLs')   // Home shows this text as before
    expect(err.invalid).toEqual(['https://example.com/x'])
  })

  it('other 400s keep being plain errors with their text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({ detail: 'No URLs provided' }, 400)))
    const err = await queueBulkAdd([]).catch(e => e)
    expect(err).not.toBeInstanceOf(InvalidLinkError)
    expect(err.message).toBe('No URLs provided')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({ detail: { message: 'Something else' } }, 400)))
    expect((await queueBulkAdd(['x']).catch(e => e)).message).toBe('Something else')
  })

  it('polling the queue with the server down still says "Cannot reach the server"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = await getQueue().catch(e => e)
    expect(err).not.toBeInstanceOf(UncertainAddError)
    expect(err.message).toBe('Cannot reach the server. Is the backend running?')
  })

  it('a 503 "database busy" is shown as that text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({ detail: 'database busy, try again' }, 503)))
    await expect(queueBulkAdd(['x'])).rejects.toThrow('database busy, try again')
  })

  it('the client waits longer than the server does for a locked database, so its 503 can arrive first', () => {
    expect(ADD_TIMEOUT_MS).toBeGreaterThan(35_000)  // db_retry.DEADLINE_S is 35 s
  })

  it('a fast answer clears the timer and returns normally', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse({ added: 1, ids: [1], invalid: [], duplicates: [] })))
    expect((await queueBulkAdd(['x'])).added).toBe(1)
    expect(vi.getTimerCount()).toBe(0)
  })
})
