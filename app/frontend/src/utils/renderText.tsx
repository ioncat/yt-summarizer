/**
 * Render text with ## chapter headings as <h3> elements.
 * Used in ResultPage and BenchmarkPage.
 */
export function renderText(text: string) {
  const blocks = text.split('\n\n')
  return blocks.map((block, i) => {
    if (block.startsWith('## ')) {
      return <h3 key={i} className="chapter-heading">{block.slice(3)}</h3>
    }
    return <p key={i} className="text-paragraph">{block}</p>
  })
}
