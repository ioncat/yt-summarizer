/** How the mind map is fitted into its canvas (NS-17 item 7).
 *
 *  markmap's own fit() picks the scale that makes the whole map fit the canvas and nothing else: for a big map that can be
 *  0.3, which shows 16 px text at 5 px. Here the scale is kept between MIN_SCALE and MAX_SCALE. When the whole map does not fit at
 *  MIN_SCALE, the map is shown at MIN_SCALE with the root in view (the user pans and zooms for the rest).
 *
 *  One fit at a time per map: a newer request makes the one in flight stop after the step it is on, so two overlapping fits (a
 *  resize and the tab becoming visible, say) cannot mix their steps. The last step is always computed from the scale the map REALLY
 *  has when it runs (read from the drawing), never from what an earlier step was expected to leave. */
export const MIN_SCALE = 0.8
export const MAX_SCALE = 1.5
export const FIT_RATIO = 0.9

interface Rect { x1: number; x2: number; y1: number; y2: number }

/** The scale at which the whole map just fits the canvas (what markmap's fit() would use, without its upper limit). */
export function wholeMapScale(rect: Rect, width: number, height: number, ratio = FIT_RATIO): number {
  const w = rect.x2 - rect.x1
  const h = rect.y2 - rect.y1
  if (w <= 0 || h <= 0 || width <= 0 || height <= 0) return 1
  return Math.min((width / w) * ratio, (height / h) * ratio)
}

/** Are the nodes laid out? Before markmap's first layout the rectangle is empty, infinite or NaN. */
export function isLaidOut(rect: Rect | undefined): boolean {
  if (!rect) return false
  const values = [rect.x1, rect.x2, rect.y1, rect.y2]
  return values.every(Number.isFinite) && rect.x2 - rect.x1 > 0 && rect.y2 - rect.y1 > 0
}

/** The subset of markmap's Markmap that fitting uses. */
export interface FittableMap {
  state: { rect: Rect; data?: unknown }
  fit(maxScale?: number): Promise<void>
  rescale(scale: number): Promise<void>
  ensureVisible(node: never, padding?: { left?: number; top?: number }): Promise<void>
}

/** The scale the drawing has now: markmap writes "translate(x,y) scale(k)" on the root group of the svg. */
export function currentScale(svg: Element): number | null {
  const g = svg.querySelector('g')
  const k = /scale\(\s*([-\d.eE+]+)/.exec(g?.getAttribute('transform') ?? '')?.[1]
  const n = k === undefined ? NaN : Number(k)
  return Number.isFinite(n) && n > 0 ? n : null
}

const inFlight = new WeakMap<object, number>()

/** Fit the map into the svg. Resolves true when it fitted (or was replaced by a newer fit, which will), false when it could not:
 *  the svg has no size (hidden), or the nodes are not laid out yet - the caller tries again a moment later. */
export async function fitMindmap(mm: FittableMap, svg: Element): Promise<boolean> {
  const mine = (inFlight.get(mm) ?? 0) + 1
  inFlight.set(mm, mine)
  const stale = () => inFlight.get(mm) !== mine

  const { width, height } = svg.getBoundingClientRect()
  if (!(width > 0 && height > 0)) return false                 // hidden: nothing to measure (items 10 / 16)
  if (!isLaidOut(mm.state.rect)) return false                  // markmap has not positioned the nodes yet
  const whole = wholeMapScale(mm.state.rect, width, height)
  await mm.fit(MAX_SCALE)                                      // the whole map, never larger than MAX_SCALE
  if (stale()) return true                                     // a newer fit took over
  if (whole >= MIN_SCALE) return true
  const now = currentScale(svg) ?? Math.min(whole, MAX_SCALE)  // what fit() really left
  if (Math.abs(now - MIN_SCALE) > 0.01) await mm.rescale(MIN_SCALE / now)    // too big to show whole: readable size instead
  if (stale()) return true
  if (mm.state.data) await mm.ensureVisible(mm.state.data as never, { left: 24, top: 24 })   // the root kept in view
  return true
}
