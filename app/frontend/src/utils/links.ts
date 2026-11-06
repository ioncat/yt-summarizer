/** One link out of a pasted line: "URL | title", trailing punctuation and quotes are dropped (the server cleans the same way). */
export function linkOfLine(line: string): string {
  const match = line.match(/https?:\/\/[^\s|"'<>]+/)
  if (!match) return line.trim()
  return match[0].replace(/[,;.:!?]+$/, '')
}

/** The field after a successful add: empty if it still holds exactly what was sent, otherwise only the lines that were sent are
 *  taken out, so a link pasted while the request was running is not lost. */
export function withoutSentLinks(current: string, sentText: string, sent: string[]): string {
  if (current === sentText) return ''
  const gone = new Set(sent)
  return current.split(/\r?\n/).filter(line => !gone.has(linkOfLine(line.trim()))).join('\n')
}

/** The links of a pasted text: one per line, empty lines dropped. A lone link and a list go the same way. */
export function parseLinks(text: string): string[] {
  return text.split(/\r?\n/).map(l => linkOfLine(l.trim())).filter(l => l.length > 0)
}
