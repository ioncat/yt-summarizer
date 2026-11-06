/** How the mind map is fitted into its canvas (NS-17 item 7).
 *
 *  markmap's own fit() picks the scale that makes the whole map fit the canvas and nothing else: for a big map that can be
 *  0.3, which shows 16 px text at 5 px. Here the scale is kept between MIN_SCALE and MAX_SCALE. When the whole map does not fit at
 *  MIN_SCALE, the map is shown at MIN_SCALE with the root in view (the user pans and zooms for the rest). */
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

/** The subset of markmap's Markmap that fitting uses. */
export interface FittableMap {
  state: { rect: Rect; data?: unknown }
  fit(maxScale?: number): Promise<void>
  rescale(scale: number): Promise<void>
  ensureVisible(node: never, padding?: { left?: number; top?: number }): Promise<void>
}

export async function fitMindmap(mm: FittableMap, svg: Element): Promise<void> {
  const { width, height } = svg.getBoundingClientRect()
  if (!(width > 0 && height > 0)) return                      // hidden: nothing to measure (items 10 / 16)
  const whole = wholeMapScale(mm.state.rect, width, height)
  await mm.fit(MAX_SCALE)                                      // the whole map, never larger than MAX_SCALE
  if (whole >= MIN_SCALE) return
  await mm.rescale(MIN_SCALE / whole)                          // too big to show whole: readable size instead, root kept in view
  if (mm.state.data) await mm.ensureVisible(mm.state.data as never, { left: 24, top: 24 })
}
