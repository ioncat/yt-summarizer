import { Fragment } from 'react'

/**
 * Render text with ## chapter headings as <h3> elements.
 * Used in ResultPage and BenchmarkPage.
 *
 * Handles two block shapes:
 *   1. "## Heading"                       → single <h3>
 *   2. "## Heading\nbody text..."         → <h3> + <p> (LLM often uses
 *      a single newline between heading and body; this would otherwise
 *      cause the whole block to render as a bolded heading)
 */
export function renderText(text: string) {
  const blocks = text.split('\n\n')
  return blocks.map((block, i) => {
    if (block.startsWith('## ')) {
      const nl = block.indexOf('\n')
      if (nl === -1) {
        return <h3 key={i} className="chapter-heading">{block.slice(3)}</h3>
      }
      const heading = block.slice(3, nl).trim()
      const body = block.slice(nl + 1).trim()
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
