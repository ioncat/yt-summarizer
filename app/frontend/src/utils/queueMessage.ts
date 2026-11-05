// The line History shows after "add the selected videos to the queue by id" (NS-25): what was added, and WHY a video was not.
export interface QueueAddByIdResult {
  added: number
  duplicates: string[]
  missing: string[]
  duplicate_details?: Array<{ video_id: string | null; reason: string; stages?: string[]; message?: string }>
}

const NAME: Record<string, string> = { cleanup: 'cleanup', summary: 'summary', mindmap: 'mind map' }

export function queueAddMessage(res: QueueAddByIdResult): string {
  const gone = res.missing.length ? ` (${res.missing.length} not found)` : ''
  const details = res.duplicate_details ?? []
  const wrongOrder = details.filter(d => d.reason === 'order')
  const queued = details.filter(d => d.reason !== 'order')
  const parts: string[] = []
  if (queued.length) {
    const stages = [...new Set(queued.flatMap(d => d.stages ?? []))].map(s => NAME[s] ?? s)
    parts.push(`${queued.length} already in the queue${stages.length ? `: ${stages.join(', ')}` : ''}`)
  }
  if (wrongOrder.length === 1 && wrongOrder[0].message) parts.push(wrongOrder[0].message.replace(/, then try again\.$/, '').replace(/\.$/, ''))
  else if (wrongOrder.length) parts.push(`${wrongOrder.length} not added: a later step is already queued and would run first`)
  if (!details.length && res.duplicates.length) parts.push(`${res.duplicates.length} already in the queue`)
  const why = parts.map(p => ` (${p})`).join('')
  const head = res.added === 0 && parts.length ? 'Nothing added to the queue' : `Added ${res.added} video${res.added !== 1 ? 's' : ''} to queue`
  return `${head}${why}${gone}`
}
