import { queueBulkAddByIds } from '../../api'

/** What became of the "Download" box for a video that was already processed (NS-17 item 12 review): the add reported it as a duplicate
 *  and queued nothing, so the download is queued by itself, by id. */
export type DownloadAnswer = 'queued' | 'already' | 'failed'

export async function queueDownloadsForExisting(videoIds: string[]): Promise<Record<string, DownloadAnswer>> {
  const ids = [...new Set(videoIds)]
  const answers: Record<string, DownloadAnswer> = {}
  try {
    const res = await queueBulkAddByIds(ids, ['download'])
    for (const id of ids) {
      answers[id] = res.missing.includes(id) ? 'failed' : res.duplicates.includes(id) ? 'already' : 'queued'
    }
  } catch {
    for (const id of ids) answers[id] = 'failed'
  }
  return answers
}

export const DOWNLOAD_TEXT: Record<DownloadAnswer, string> = {
  queued: 'download queued',
  already: 'download already queued',
  failed: 'the download could not be queued',
}
