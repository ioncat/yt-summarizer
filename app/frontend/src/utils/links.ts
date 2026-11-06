/** One link out of a pasted line: "URL | title", trailing punctuation and quotes are dropped (the server cleans the same way). */
export function linkOfLine(line: string): string {
  const match = line.match(/https?:\/\/[^\s|"'<>]+/)
  if (!match) return line.trim()
  return match[0].replace(/[,;.:!?]+$/, '')
}

/** The links of a pasted text: one per line, empty lines dropped. A lone link and a list go the same way. */
export function parseLinks(text: string): string[] {
  return text.split(/\r?\n/).map(l => linkOfLine(l.trim())).filter(l => l.length > 0)
}
