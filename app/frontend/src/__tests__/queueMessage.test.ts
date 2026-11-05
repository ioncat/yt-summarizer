import { describe, it, expect } from 'vitest'
import { queueAddMessage } from '../utils/queueMessage'

const base = { added: 0, duplicates: [], missing: [] }

describe('queueAddMessage (History, add by id)', () => {
  it('says what was added, as before', () => {
    expect(queueAddMessage({ ...base, added: 2 })).toBe('Added 2 videos to queue')
    expect(queueAddMessage({ ...base, added: 1, duplicates: ['a'], missing: ['x'] })).toBe('Added 1 video to queue (1 already in the queue) (1 not found)')
  })

  it('says why a refused add was refused: the order', () => {
    const msg = queueAddMessage({ ...base, duplicates: ['v'], duplicate_details: [{ video_id: 'v', reason: 'order', stages: ['mindmap'],
      message: 'A mind map is already queued and would run before the cleanup and summary: wait for it or remove it on the Queue page, then try again.' }] })
    expect(msg).toBe('Nothing added to the queue (A mind map is already queued and would run before the cleanup and summary: wait for it or remove it on the Queue page)')
  })

  it('says which stages are already queued', () => {
    const msg = queueAddMessage({ ...base, duplicates: ['v'], duplicate_details: [{ video_id: 'v', reason: 'in_queue', stages: ['cleanup', 'summary'] }] })
    expect(msg).toBe('Nothing added to the queue (1 already in the queue: cleanup, summary)')
  })

  it('mixes added, queued and wrong-order videos, and counts several wrong-order ones', () => {
    const msg = queueAddMessage({ added: 1, duplicates: ['a', 'b', 'c'], missing: [], duplicate_details: [
      { video_id: 'a', reason: 'in_queue', stages: ['summary'] },
      { video_id: 'b', reason: 'order', stages: ['mindmap'], message: 'x' },
      { video_id: 'c', reason: 'order', stages: ['summary'], message: 'y' },
    ] })
    expect(msg).toBe('Added 1 video to queue (1 already in the queue: summary) (2 not added: a later step is already queued and would run first)')
  })
})
