import { Fragment } from 'react'

/**
 * Render text with ## chapter headings as <h3> elements.
 * Used in ResultPage and BenchmarkPage.
 *
 * Defensive against malformed LLM output where '## ' markers appear
 * mid-paragraph without surrounding blank lines. We:
 *   1. Normalize: insert blank lines before every '## ' marker so the
 *      split('\n\n') step produces one block per heading.
 *   2. Within each '## ' block, separate heading from body using the first
 *      newline, sentence terminator + space + capital, or word-boundary
 *      cut at 120 chars.
 *
 * The backend already normalizes new summaries (services/text_utils.py),
 * but this layer rescues legacy DB rows produced before that fix shipped.
 */

const HEADING_MAX = 120
const SENT_BREAK = /[.!?…]\s+(?=[A-ZА-ЯЁ])/

function splitHeadingBody(section: string): { heading: string; body: string } {
  const nl = section.indexOf('\n')
  const sentMatch = section.slice(0, 250).match(SENT_BREAK)
  const sentCut = sentMatch && sentMatch.index !== undefined
    ? sentMatch.index + sentMatch[0].length - 1  // keep terminator with heading
    : -1

  let cut = -1
  if (nl >= 0) cut = nl
  if (sentCut >= 0) cut = cut < 0 ? sentCut : Math.min(cut, sentCut)

  if (cut < 0 && section.length > HEADING_MAX) {
    const ws = section.lastIndexOf(' ', HEADING_MAX)
    if (ws > 0) cut = ws
  }

  if (cut < 0) {
    return { heading: section.trim(), body: '' }
  }
  return {
    heading: section.slice(0, cut).trim(),
    body: section.slice(cut).trim(),
  }
}

export function renderText(text: string) {
  // Normalize: ensure '\n\n' before every '## ' (skip if at very start).
  const normalized = text.replace(/(?:^|[ \t]*\n?)##\s+/g, (_m, offset) =>
    offset === 0 ? '## ' : '\n\n## '
  )

  const blocks = normalized.split('\n\n').filter(b => b.trim().length > 0)
  return blocks.map((block, i) => {
    if (block.startsWith('## ')) {
      const { heading, body } = splitHeadingBody(block.slice(3))
      if (!heading) {
        return body ? <p key={i} className="text-paragraph">{body}</p> : null
      }
      return (
        <Fragment key={i}>
          <h3 className="chapter-heading">{heading}</h3>
          {body && <p className="text-paragraph">{body}</p>}
        </Fragment>
      )
    }
    return <p key={i} className="text-paragraph">{block}</p>
  })
}
