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
