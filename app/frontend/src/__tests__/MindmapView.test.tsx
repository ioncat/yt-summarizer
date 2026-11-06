import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'

// NS-17 items 7 / 10 / 16: markmap throws SVGLength errors and lays out at NaN or a tiny scale when it is drawn while the svg is
// hidden or has no size. The view must draw only once the svg has a size, fit it at a readable scale, and fit it again when the size
// changes (tab visible, window resized). markmap itself is replaced by a recorder.
const fit = vi.fn(() => Promise.resolve())
const rescale = vi.fn(() => Promise.resolve())
const ensureVisible = vi.fn(() => Promise.resolve())
const destroy = vi.fn()
const setData = vi.fn(() => Promise.resolve())
let rect = { x1: 0, y1: 0, x2: 500, y2: 400 }       // the laid-out map, in map units
const create = vi.fn(() => ({ setData, fit, rescale, ensureVisible, destroy, state: { get rect() { return rect }, data: { root: true } } }))

vi.mock('markmap-lib', () => ({ Transformer: class { transform() { return { root: { content: 'root' } } } } }))
vi.mock('markmap-view', () => ({ Markmap: { create: (...a: unknown[]) => (create as (...x: unknown[]) => unknown)(...a) } }))

import MindmapView from '../components/MindmapView'
import { MIN_SCALE, MAX_SCALE, wholeMapScale } from '../components/mindmapFit'

let size = { width: 0, height: 0 }
let observers: Array<{ cb: () => void; observe: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }> = []

beforeEach(() => {
  vi.clearAllMocks()
  size = { width: 0, height: 0 }
  rect = { x1: 0, y1: 0, x2: 500, y2: 400 }
  observers = []
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(() => ({ ...size, x: 0, y: 0, top: 0, left: 0, right: size.width, bottom: size.height, toJSON() {} }))
  vi.stubGlobal('ResizeObserver', class {
    observe = vi.fn()
    disconnect = vi.fn()
    constructor(public cb: () => void) { observers.push(this as never) }
  })
})

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('MindmapView draws only when it has a size', () => {
  it('does not touch markmap while the svg has no size (hidden tab)', () => {
    render(<MindmapView text="# A" />)
    expect(create).not.toHaveBeenCalled()
    expect(observers).toHaveLength(1)
    expect(observers[0].observe).toHaveBeenCalled()
  })

  it('draws and fits when the svg gets a size', async () => {
    render(<MindmapView text="# A" />)
    size = { width: 900, height: 800 }
    act(() => observers[0].cb())
    expect(create).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(fit).toHaveBeenCalledTimes(1))
  })

  it('a size callback that still says "no size" draws nothing', () => {
    render(<MindmapView text="# A" />)
    act(() => observers[0].cb())
    expect(create).not.toHaveBeenCalled()
  })

  it('draws at once when the svg already has a size, and fits once', async () => {
    size = { width: 900, height: 800 }
    render(<MindmapView text="# A" />)
    expect(create).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(fit).toHaveBeenCalledTimes(1))
    act(() => observers[0].cb())                                           // the observer's first report, same size: no second fit
    await new Promise(r => setTimeout(r, 200))
    expect(fit).toHaveBeenCalledTimes(1)
  })

  it('leaving while it waits for a size draws nothing and stops watching', () => {
    const view = render(<MindmapView text="# A" />)
    view.unmount()
    expect(observers[0].disconnect).toHaveBeenCalled()
    size = { width: 900, height: 800 }
    act(() => observers[0].cb())
    expect(create).not.toHaveBeenCalled()
  })

  it('a new text updates the existing map instead of creating a second one', async () => {
    size = { width: 900, height: 800 }
    const view = render(<MindmapView text="# A" />)
    view.rerender(<MindmapView text="# B" />)
    expect(create).toHaveBeenCalledTimes(1)
    expect(setData).toHaveBeenCalledTimes(2)
  })
})

describe('MindmapView fits again when the size changes (NS-17 item 7)', () => {
  it('a window resize / the tab becoming visible fits again once the size has settled; a hidden size does not', async () => {
    size = { width: 900, height: 800 }
    render(<MindmapView text="# A" />)
    await waitFor(() => expect(fit).toHaveBeenCalledTimes(1))
    vi.useFakeTimers()
    size = { width: 0, height: 0 }                                          // hidden: nothing happens
    act(() => observers[0].cb())
    vi.advanceTimersByTime(500)
    expect(fit).toHaveBeenCalledTimes(1)
    size = { width: 640, height: 800 }                                      // visible again, narrower
    act(() => observers[0].cb())
    size = { width: 650, height: 800 }                                      // a drag of the window edge: many reports ...
    act(() => observers[0].cb())
    expect(fit).toHaveBeenCalledTimes(1)                                    // ... no fit while it moves
    await act(async () => { vi.advanceTimersByTime(200) })
    expect(fit).toHaveBeenCalledTimes(2)                                    // ... one when it settles
  })

  it('"Fit" fits at the readable scale, and does nothing while the svg has no size', async () => {
    size = { width: 900, height: 800 }
    render(<MindmapView text="# A" />)
    await waitFor(() => expect(fit).toHaveBeenCalledTimes(1))
    size = { width: 0, height: 0 }
    fireEvent.click(screen.getByText(/Fit/))
    await new Promise(r => setTimeout(r, 20))
    expect(fit).toHaveBeenCalledTimes(1)
    size = { width: 900, height: 800 }
    fireEvent.click(screen.getByText(/Fit/))
    await waitFor(() => expect(fit).toHaveBeenCalledTimes(2))
    expect(fit).toHaveBeenLastCalledWith(MAX_SCALE)
  })
})

describe('the scale of the fit', () => {
  it('a small map is not blown up beyond MAX_SCALE (fit gets the limit)', async () => {
    size = { width: 900, height: 800 }
    rect = { x1: 0, y1: 0, x2: 100, y2: 60 }
    render(<MindmapView text="# A" />)
    await waitFor(() => expect(fit).toHaveBeenCalledWith(MAX_SCALE))
    expect(rescale).not.toHaveBeenCalled()
  })

  it('a map that fits at a readable scale is fitted whole', async () => {
    size = { width: 900, height: 800 }
    rect = { x1: 0, y1: 0, x2: 1000, y2: 700 }                              // whole-map scale 0.81: above MIN_SCALE
    expect(wholeMapScale(rect, 900, 800)).toBeGreaterThanOrEqual(MIN_SCALE)
    render(<MindmapView text="# A" />)
    await waitFor(() => expect(fit).toHaveBeenCalledTimes(1))
    expect(rescale).not.toHaveBeenCalled()
  })

  it('a map that would need a tiny scale is shown at MIN_SCALE with the root in view, not as a 5 px blob', async () => {
    size = { width: 638, height: 800 }
    rect = { x1: 0, y1: 0, x2: 1700, y2: 2000 }                             // whole-map scale ~0.29
    const whole = wholeMapScale(rect, 638, 800)
    expect(whole).toBeLessThan(MIN_SCALE)
    render(<MindmapView text="# A" />)
    await waitFor(() => expect(rescale).toHaveBeenCalledTimes(1))
    expect(rescale.mock.calls[0]).toEqual([MIN_SCALE / whole])               // fit gave `whole`; this brings it to MIN_SCALE
    await waitFor(() => expect(ensureVisible).toHaveBeenCalledTimes(1))
  })
})

describe('wholeMapScale', () => {
  it('is the scale at which the map just fits, with the fit ratio', () => {
    expect(wholeMapScale({ x1: 0, y1: 0, x2: 900, y2: 400 }, 900, 800)).toBeCloseTo(0.9)
    expect(wholeMapScale({ x1: 0, y1: 0, x2: 400, y2: 1600 }, 900, 800)).toBeCloseTo(0.45)
  })

  it('does not divide by zero for an empty map or no canvas', () => {
    expect(wholeMapScale({ x1: 0, y1: 0, x2: 0, y2: 0 }, 900, 800)).toBe(1)
    expect(wholeMapScale({ x1: 0, y1: 0, x2: 10, y2: 10 }, 0, 0)).toBe(1)
  })
})

// --- NS-17 item 7, reviewer's fix: one fit at a time, an absolute final scale, and nodes that are not laid out yet -------------

import { fitMindmap, currentScale, isLaidOut } from '../components/mindmapFit'

/** A map that behaves like markmap's: fit() and rescale() change the scale of the drawing's root group when their transition ends
 *  (here: when the test lets them), rescale() MULTIPLIES the scale it finds, fit() sets an absolute one. */
function fakeMap(svg: SVGSVGElement, rectNow: { x1: number; y1: number; x2: number; y2: number }) {
  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g')
  g.setAttribute('transform', 'translate(0,0) scale(1)')
  svg.appendChild(g)
  const pending: Array<() => void> = []
  const log: string[] = []
  const wait = (apply: () => void) => new Promise<void>(res => { pending.push(() => { apply(); res() }) })
  const mm = {
    state: { rect: rectNow, data: { root: true } },
    fit: vi.fn((max = 2) => {
      const { width, height } = svg.getBoundingClientRect()
      const k = Math.min(width / (mm.state.rect.x2 - mm.state.rect.x1) * 0.9, height / (mm.state.rect.y2 - mm.state.rect.y1) * 0.9, max)
      log.push(`fit>${k.toFixed(2)}`)
      return wait(() => g.setAttribute('transform', `translate(0,0) scale(${k})`))
    }),
    rescale: vi.fn((factor: number) => {
      const k = (currentScale(svg) ?? 1) * factor
      log.push(`rescale*${factor.toFixed(2)}`)
      return wait(() => g.setAttribute('transform', `translate(0,0) scale(${k})`))
    }),
    ensureVisible: vi.fn(() => { log.push('visible'); return Promise.resolve() }),
  }
  const flush = async () => { while (pending.length) { pending.shift()!(); await Promise.resolve(); await Promise.resolve() } }
  return { mm, flush, log, scale: () => currentScale(svg) }
}

describe('two overlapping fits (reviewer: wrong scale, sometimes far above the limit)', () => {
  it('the older fit stops after its step; the map ends at the readable scale, never compounded', async () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg') as SVGSVGElement
    size = { width: 638, height: 800 }
    const { mm, flush, scale } = fakeMap(svg, { x1: 0, y1: 0, x2: 1700, y2: 2000 })          // whole-map scale ~0.29
    const first = fitMindmap(mm as never, svg)                                                // resize ...
    const second = fitMindmap(mm as never, svg)                                               // ... and the tab becoming visible
    await flush()
    await flush()
    await flush()
    await Promise.all([first, second])
    expect(scale()).toBeCloseTo(MIN_SCALE, 2)                                                 // not 0.8 * 2.7 * ...
    expect(mm.rescale).toHaveBeenCalledTimes(1)                                               // the older fit did not rescale
  })

  it('a new size between two steps: the last fit decides, from the size it measured', async () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg') as SVGSVGElement
    size = { width: 638, height: 800 }
    const { mm, flush, scale } = fakeMap(svg, { x1: 0, y1: 0, x2: 300, y2: 200 })             // small map: fits above 1.5 -> limited
    const first = fitMindmap(mm as never, svg)
    size = { width: 1400, height: 900 }
    const second = fitMindmap(mm as never, svg)
    await flush(); await flush(); await flush()
    await Promise.all([first, second])
    expect(scale()).toBeCloseTo(MAX_SCALE, 2)
    expect(scale()!).toBeLessThanOrEqual(MAX_SCALE + 0.001)
  })

  it('three fits in a row (resize drag) leave one rescale at most and the right scale', async () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg') as SVGSVGElement
    size = { width: 638, height: 800 }
    const { mm, flush, scale } = fakeMap(svg, { x1: 0, y1: 0, x2: 1700, y2: 2000 })
    const all = [fitMindmap(mm as never, svg), fitMindmap(mm as never, svg), fitMindmap(mm as never, svg)]
    for (let i = 0; i < 5; i++) await flush()
    await Promise.all(all)
    expect(scale()).toBeCloseTo(MIN_SCALE, 2)
    expect(mm.rescale.mock.calls.length).toBeLessThanOrEqual(1)
  })
})

describe('nodes that are not laid out yet', () => {
  it('isLaidOut: an empty, infinite or NaN rectangle is not a layout', () => {
    expect(isLaidOut({ x1: 0, y1: 0, x2: 10, y2: 10 })).toBe(true)
    for (const bad of [{ x1: 0, y1: 0, x2: 0, y2: 0 }, { x1: Infinity, y1: 0, x2: 1, y2: 1 }, { x1: NaN, y1: 0, x2: 1, y2: 1 }]) expect(isLaidOut(bad)).toBe(false)
    expect(isLaidOut(undefined)).toBe(false)
  })

  it('fitMindmap does nothing and says so (false) while the layout is empty', async () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg') as SVGSVGElement
    size = { width: 638, height: 800 }
    const { mm } = fakeMap(svg, { x1: 0, y1: 0, x2: 0, y2: 0 })
    expect(await fitMindmap(mm as never, svg)).toBe(false)
    expect(mm.fit).not.toHaveBeenCalled()
  })

  it('the view tries again until the nodes are positioned, then fits (a sized svg with an unlaid map)', async () => {
    vi.useFakeTimers()
    size = { width: 900, height: 800 }
    rect = { x1: 0, y1: 0, x2: 0, y2: 0 }                                    // markmap has not positioned anything yet
    render(<MindmapView text="# A" />)
    await act(async () => { await vi.advanceTimersByTimeAsync(10) })
    expect(create).toHaveBeenCalledTimes(1)
    expect(fit).not.toHaveBeenCalled()
    await act(async () => { await vi.advanceTimersByTimeAsync(300) })       // a couple of retries: still nothing to fit
    expect(fit).not.toHaveBeenCalled()
    rect = { x1: 0, y1: 0, x2: 500, y2: 400 }                                // the first layout is done
    await act(async () => { await vi.advanceTimersByTimeAsync(400) })
    expect(fit).toHaveBeenCalled()
  })

  it('after the first render a settling fit runs once more when markmap\'s first transition is over', async () => {
    vi.useFakeTimers()
    size = { width: 900, height: 800 }
    render(<MindmapView text="# A" />)
    await act(async () => { await vi.advanceTimersByTimeAsync(10) })
    const afterFirst = fit.mock.calls.length
    expect(afterFirst).toBeGreaterThanOrEqual(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(500) })
    expect(fit.mock.calls.length).toBe(afterFirst + 1)
  })
})
