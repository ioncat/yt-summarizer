import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'

// NS-17 items 7 / 10 / 16: markmap throws SVGLength errors and lays out at NaN or a tiny scale when it is drawn while the svg is
// hidden or has no size. The view must draw only once the svg has a size. markmap itself is replaced by a recorder.
const fit = vi.fn()
const destroy = vi.fn()
const setData = vi.fn(() => Promise.resolve())
const create = vi.fn(() => ({ setData, fit, destroy }))

vi.mock('markmap-lib', () => ({ Transformer: class { transform() { return { root: { content: 'root' } } } } }))
vi.mock('markmap-view', () => ({ Markmap: { create: (...a: unknown[]) => (create as (...x: unknown[]) => unknown)(...a) } }))

import MindmapView from '../components/MindmapView'

let size = { width: 0, height: 0 }
let observers: Array<{ cb: () => void; observe: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }> = []

beforeEach(() => {
  vi.clearAllMocks()
  size = { width: 0, height: 0 }
  observers = []
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(() => ({ ...size, x: 0, y: 0, top: 0, left: 0, right: size.width, bottom: size.height, toJSON() {} }))
  vi.stubGlobal('ResizeObserver', class {
    observe = vi.fn()
    disconnect = vi.fn()
    constructor(public cb: () => void) { observers.push(this as never) }
  })
})

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('MindmapView draws only when it has a size', () => {
  it('does not touch markmap while the svg has no size (hidden tab)', () => {
    render(<MindmapView text="# A" />)
    expect(create).not.toHaveBeenCalled()
    expect(observers).toHaveLength(1)
    expect(observers[0].observe).toHaveBeenCalled()
  })

  it('draws and fits once, when the svg gets a size', async () => {
    render(<MindmapView text="# A" />)
    size = { width: 900, height: 800 }
    act(() => observers[0].cb())
    expect(create).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(fit).toHaveBeenCalledTimes(1))
    expect(observers[0].disconnect).toHaveBeenCalled()                    // no second draw from later size changes
    act(() => observers[0].cb())
    expect(create).toHaveBeenCalledTimes(1)
  })

  it('a size callback that still says "no size" draws nothing', () => {
    render(<MindmapView text="# A" />)
    act(() => observers[0].cb())
    expect(create).not.toHaveBeenCalled()
  })

  it('draws at once when the svg already has a size', async () => {
    size = { width: 900, height: 800 }
    render(<MindmapView text="# A" />)
    expect(create).toHaveBeenCalledTimes(1)
    expect(observers).toHaveLength(0)
    await waitFor(() => expect(fit).toHaveBeenCalledTimes(1))
  })

  it('leaving while it waits for a size draws nothing and stops watching', () => {
    const view = render(<MindmapView text="# A" />)
    view.unmount()
    expect(observers[0].disconnect).toHaveBeenCalled()
    size = { width: 900, height: 800 }
    act(() => observers[0].cb())
    expect(create).not.toHaveBeenCalled()
  })

  it('"Fit" does nothing while the svg has no size, and fits when it has', async () => {
    size = { width: 900, height: 800 }
    render(<MindmapView text="# A" />)
    await waitFor(() => expect(fit).toHaveBeenCalledTimes(1))
    size = { width: 0, height: 0 }
    fireEvent.click(screen.getByText(/Fit/))
    expect(fit).toHaveBeenCalledTimes(1)
    size = { width: 900, height: 800 }
    fireEvent.click(screen.getByText(/Fit/))
    expect(fit).toHaveBeenCalledTimes(2)
  })

  it('a new text updates the existing map instead of creating a second one', async () => {
    size = { width: 900, height: 800 }
    const view = render(<MindmapView text="# A" />)
    view.rerender(<MindmapView text="# B" />)
    expect(create).toHaveBeenCalledTimes(1)
    expect(setData).toHaveBeenCalledTimes(2)
  })
})
