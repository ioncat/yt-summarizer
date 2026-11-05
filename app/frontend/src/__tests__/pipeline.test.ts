import { describe, it, expect, beforeEach } from 'vitest'
import {
  AUTO_PIPELINE_KEY, autoPipelineStages, defaultQueueStages, readAutoPipeline, resolveStages,
} from '../utils/pipeline'

describe('shared pipeline choice (Home page and queue "New")', () => {
  beforeEach(() => localStorage.clear())

  it('with nothing stored the default is extract only', () => {
    expect(readAutoPipeline()).toBe(false)
    expect(defaultQueueStages()).toEqual(['extract'])
    expect(defaultQueueStages(true)).toEqual(['transcribe'])
  })

  it('the Home checkbox "Run full pipeline" makes the default the full pipeline', () => {
    localStorage.setItem(AUTO_PIPELINE_KEY, 'true')
    expect(defaultQueueStages()).toEqual(['extract', 'cleanup', 'summary', 'mindmap'])
    expect(defaultQueueStages(true)).toEqual(['transcribe', 'cleanup', 'summary', 'mindmap'])
    localStorage.setItem(AUTO_PIPELINE_KEY, 'false')
    expect(defaultQueueStages()).toEqual(['extract'])
  })

  it('resolveStages and autoPipelineStages are what the Home page always used', () => {
    expect(resolveStages('cleanup', false)).toEqual(['extract', 'cleanup'])
    expect(resolveStages('cleanup', true)).toEqual(['transcribe', 'cleanup'])
    expect(resolveStages('unknown', false)).toEqual(['extract'])
    expect(autoPipelineStages(false)).toEqual(['extract', 'cleanup', 'summary', 'mindmap'])
  })
})
