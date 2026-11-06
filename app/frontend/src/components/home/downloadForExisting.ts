import { queueBulkAddByIds } from '../../api'

/** What became of the "Download" box for a video that was already processed (NS-17 item 12 review): the add reported it as a duplicate
 *  and queued nothing, so the download is queued by itself, by id. */
export type DownloadAnswer = 'queued' | 'already' | 'failed'

export interface QueuedDownloads {
  answers: Record<string, DownloadAnswer>
  /** The queue item of each download that was just queued, in the order of the videos that were queued (for one video: its item),
   *  so the page can follow it. Only filled for videos whose answer is 'queued'. */
  itemOf: Record<string, number>
}

export async function queueDownloadsForExisting(videoIds: string[]): Promise<QueuedDownloads> {
  const ids = [...new Set(videoIds)]
  const answers: Record<string, DownloadAnswer> = {}
  const itemOf: Record<string, number> = {}
  try {
    const res = await queueBulkAddByIds(ids, ['download'])
    const queued = ids.filter(id => !res.missing.includes(id) && !res.duplicates.includes(id))
    for (const id of ids) {
      answers[id] = res.missing.includes(id) ? 'failed' : res.duplicates.includes(id) ? 'already' : 'queued'
    }
    queued.forEach((id, i) => { if (res.ids[i] !== undefined) itemOf[id] = res.ids[i] })     // ids come back in the order of the videos
  } catch {
    for (const id of ids) answers[id] = 'failed'
  }
  return { answers, itemOf }
}

export const DOWNLOAD_TEXT: Record<DownloadAnswer, string> = {
  queued: 'download queued',
  already: 'download already queued',
  failed: 'the download could not be queued',
}
