/**
 * Classify a video by its text length and chapter presence into one of
 * the processing-mode categories. Used for History page badges.
 *
 * Keep in sync with backend auto-select rules in api.py _run_summary().
 */

const MAP_REDUCE_THRESHOLD = 24_000
const XL_THRESHOLD = 50_000

export interface VideoType {
  key: 'short' | 'long' | 'long_structured' | 'xl'
  label: string
  emoji: string
  mode: string
}

export function classifyVideo(
  charCount: number | null,
  hasChapters: boolean | undefined,
): VideoType | null {
  if (charCount == null) return null

  if (charCount < MAP_REDUCE_THRESHOLD) {
    return { key: 'short', label: 'Short', emoji: '📄', mode: 'single-pass' }
  }
  if (hasChapters) {
    return { key: 'long_structured', label: 'Long Structured', emoji: '📚', mode: 'full_extract' }
  }
  if (charCount > XL_THRESHOLD) {
    return { key: 'xl', label: 'XL', emoji: '📕', mode: 'hierarchical (planned)' }
  }
  return { key: 'long', label: 'Long', emoji: '📑', mode: 'map-reduce' }
}
