import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StageTable } from '../components/result/StageTable'
import type { ResultResponse, StageRun } from '../api'

const run = (over: Partial<StageRun> = {}): StageRun => ({
  attempt: 1, status: 'done', queue_item_id: 3, model: 'qwen', started_at: '2026-11-01T10:00:00', finished_at: '2026-11-01T10:02:05',
  error_code: null, error_text: null, meta: {}, progress_done: null, progress_total: null, runs: 1, last_done: null, ...over,
})
const result = (stages: ResultResponse['stages']) => ({ video_id: 'v', stages } as ResultResponse)

describe('StageTable (NS-25)', () => {
  it('shows nothing for a video with no recorded runs', () => {
    const { container } = render(<StageTable result={result({})} />)
    expect(container.firstChild).toBeNull()
    expect(render(<StageTable result={{ video_id: 'v' } as ResultResponse} />).container.firstChild).toBeNull()
  })

  it('lists the steps that ran, with status, model and how long the saved result took', () => {
    render(<StageTable result={result({ cleanup: run({ model: 'gemma' }), summary: run({ model: 'qwen' }) })} />)
    expect(screen.getByText('Processing steps (2)')).toBeTruthy()
    expect(screen.getByText('Cleanup')).toBeTruthy()
    expect(screen.getByText('gemma')).toBeTruthy()
    expect(screen.getAllByText('done')).toHaveLength(2)
    expect(screen.getAllByText(/2:05/)).toHaveLength(2)
    expect(document.querySelector('details')!.open).toBe(false)     // all fine: collapsed
  })

  it('a failed step opens the table, says why in plain words, and shows the model of the earlier successful run', () => {
    const good = run({ model: 'model-good' })
    render(<StageTable result={result({
      summary: run({ status: 'failed', attempt: 2, runs: 2, model: 'model-bad', error_code: 'empty_answer',
        error_text: 'model returned nothing', last_done: good }),
    })} />)
    expect(document.querySelector('details')!.open).toBe(true)
    expect(screen.getByText('failed')).toBeTruthy()
    expect(screen.getByText('the model returned nothing')).toBeTruthy()
    expect(screen.getByText('model returned nothing')).toBeTruthy()
    expect(screen.getByText('model-good')).toBeTruthy()
    expect(screen.queryByText('model-bad')).toBeNull()
    expect(screen.getByText(/Showing the earlier successful run \(model-good\)/)).toBeTruthy()
    expect(screen.getByText('2 runs so far')).toBeTruthy()
  })

  it('a running or stopped step is named as such', () => {
    render(<StageTable result={result({
      cleanup: run({ status: 'processing', finished_at: null }),
      mindmap: run({ status: 'cancelled', finished_at: null }),
    })} />)
    expect(screen.getByText('running')).toBeTruthy()
    expect(screen.getByText('stopped')).toBeTruthy()
  })
})
