const BASE = '/api'

// Adding to the queue: longer than the server's own ceiling for a locked database (about 30 s for one step, see
// services/db_retry.py), so a busy database normally ends in the server's 503 "database busy" and not in a client timeout.
export const ADD_TIMEOUT_MS = 40_000
export const POLL_TIMEOUT_MS = 10_000  // one poll of the queue list

export const ADD_TIMEOUT_HINT = 'The link may have been added: check the queue before retrying.'
const POLL_TIMEOUT_HINT = 'The server may be busy or not running.'

/** The server refused every link of an add as not a YouTube link (400 "No valid YouTube URLs"). Not a failure to retry. */
export class InvalidLinkError extends Error {
  constructor(public readonly invalid: string[] = []) {
    super('No valid YouTube URLs')
    this.name = 'InvalidLinkError'
  }
}

/** An add whose answer never arrived (timeout or a lost connection): the server may well have added the link. */
export class UncertainAddError extends Error {}

/** fetch that gives up after `ms` (NS-28): a hung request becomes an error the page can show, with a Retry.
 *  With `uncertain` (an add), no answer at all - timeout or network failure - is an UncertainAddError that says the
 *  link may have been added; for other calls a network failure is "Cannot reach the server". */
export async function fetchWithTimeout(
  input: string, init: RequestInit = {}, ms = ADD_TIMEOUT_MS, hint = ADD_TIMEOUT_HINT, uncertain = false,
): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), ms)
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } catch (err) {
    if (controller.signal.aborted) {
      const message = `No answer from the server in ${Math.round(ms / 1000)} s. ${hint}`
      throw uncertain ? new UncertainAddError(message) : new Error(message)
    }
    if (err instanceof TypeError) {
      if (uncertain) throw new UncertainAddError(`No answer from the server. ${hint}`)
      throw new Error('Cannot reach the server. Is the backend running?')
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

/** The message of an error response body. `detail` is a string, an object with `message`, or - for a request
 *  the server refused to parse (422) - a list of problems; a list must never end up as "[object Object]". */
export function errorText(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const first = detail[0] as { type?: string; msg?: string; ctx?: { max_length?: number } } | undefined
    if (first?.type === 'too_long' && first.ctx?.max_length) return `Too many items (max ${first.ctx.max_length} per request)`
    if (first?.msg) return first.msg
    return fallback
  }
  const message = (detail as { message?: unknown } | undefined)?.message
  if (typeof message === 'string' && message) return message
  return fallback
}

export interface ProcessResponse {
  task_id: string
  video_id: string
}

export interface StatusResponse {
  task_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  progress_text?: string | null
  error_message: string | null
  available_languages: string[] | null
}

export interface ResultResponse {
  video_id: string
  url: string
  title: string | null
  author: string | null
  duration: number | null
  language: string | null
  formatted_text: string | null
  cleaned_text: string | null
  cleanup_status: 'processing' | 'done' | 'failed' | null
  cleanup_model: string | null
  cleanup_duration_seconds: number | null
  cleanup_paragraphs_done: number | null
  cleanup_paragraphs_total: number | null
  summary_text: string | null
  summary_status: 'processing' | 'done' | 'failed' | null
  summary_model: string | null
  summary_mode: 'single' | 'map_reduce' | 'full_extract' | null
  summary_chunks_count: number | null
  summary_chunks_done: number | null
  summary_chunks_total: number | null
  summary_duration_seconds: number | null
  char_count: number | null
  chapters: Array<{ start_time: number; end_time: number; title: string }> | null
  reextract_in_progress?: boolean
  retranscribe_progress?: string | null
  created_at: string
  cleanup_finished_at: string | null
  summary_finished_at: string | null
  chat_history: Array<{ role: string; content: string }> | null
  mindmap_text: string | null
  mindmap_status: 'processing' | 'done' | 'failed' | null
  cleanup_error?: string | null
  summary_error?: string | null
  mindmap_error?: string | null
  is_favorite: boolean
  subtitle_source?: 'captions' | 'transcript' | null
  subtitles_type?: string | null
  transcription_duration_seconds?: number | null
  transcription_model?: string | null
  transcription_device?: string | null
  transcription_finished_at?: string | null
}

export interface HistoryItem {
  video_id: string
  url?: string
  title: string | null
  author: string | null
  language: string | null
  char_count: number | null
  has_chapters?: boolean
  has_cleaned?: boolean
  has_summary?: boolean
  is_favorite?: boolean
  subtitle_source?: 'captions' | 'transcript' | null
  created_at: string
}

export interface HistoryResponse {
  page: number
  items: HistoryItem[]
}

export class VideoAlreadyExistsError extends Error {
  constructor(public readonly videoId: string) {
    super('Video already processed')
  }
}

export async function processVideo(
  url: string,
  language: string,
  enableCleanup = false,
): Promise<ProcessResponse> {
  const res = await fetch(`${BASE}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, language, enable_cleanup: enableCleanup }),
  })
  if (res.status === 409) {
    const body = await res.json()
    throw new VideoAlreadyExistsError(body.detail?.video_id ?? body.detail)
  }
  if (!res.ok) throw new Error((await res.json()).detail || 'Error')
  return res.json()
}

export async function getStatus(taskId: string): Promise<StatusResponse> {
  const res = await fetch(`${BASE}/status/${encodeURIComponent(taskId)}`)
  if (!res.ok) throw new Error('Status not found')
  return res.json()
}

export async function getResult(videoId: string): Promise<ResultResponse> {
  const res = await fetch(`${BASE}/result/${encodeURIComponent(videoId)}`)
  if (res.status === 404) throw new Error('Result not found')
  if (!res.ok) throw new Error('Failed to load result')
  return res.json()
}

export async function getHistory(page = 1, search?: string, favoritesOnly = false): Promise<HistoryResponse> {
  const params = new URLSearchParams({ page: String(page) })
  if (search) params.set('search', search)
  if (favoritesOnly) params.set('favorites_only', 'true')
  const res = await fetch(`${BASE}/history?${params}`)
  if (!res.ok) throw new Error('Failed to load history')
  return res.json()
}

export async function toggleFavorite(videoId: string): Promise<{ is_favorite: boolean }> {
  const res = await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/favorite`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to toggle favorite')
  return res.json()
}

export async function deleteResult(videoId: string): Promise<void> {
  const res = await fetch(`${BASE}/result/${encodeURIComponent(videoId)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete')
}

export async function deleteResultsBulk(videoIds: string[]): Promise<{ deleted: number; not_found: number }> {
  const res = await fetch(`${BASE}/history/delete-bulk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_ids: videoIds }),
  })
  if (!res.ok) throw new Error('Failed to bulk delete')
  return res.json()
}

export async function cancelCleanup(videoId: string): Promise<void> {
  await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/cleanup`, { method: 'DELETE' })
}

export async function startSummary(videoId: string): Promise<void> {
  const res = await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/summary`, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Failed to start summarization'))
  }
}

export async function cancelSummary(videoId: string): Promise<void> {
  await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/summary`, { method: 'DELETE' })
}

/** Queue the mind map. {status:'done', mindmap_text} = the saved map (nothing queued, unless force); {status:'processing'} = queued. */
export async function startMindmap(videoId: string, force = false): Promise<{ status: string; mindmap_text?: string }> {
  const url = force
    ? `${BASE}/result/${encodeURIComponent(videoId)}/mindmap?force=true`
    : `${BASE}/result/${encodeURIComponent(videoId)}/mindmap`
  const res = await fetch(url, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Failed to start mindmap generation'))
  }
  return res.json()
}

export async function cancelMindmap(videoId: string): Promise<void> {
  await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/mindmap`, { method: 'DELETE' })
}

export async function startCleanup(videoId: string): Promise<void> {
  const res = await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/cleanup`, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Failed to start cleanup'))
  }
}

export async function saveChatHistory(
  videoId: string,
  messages: Array<{ role: string; content: string }>
): Promise<void> {
  await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/chat`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })
}

export async function clearChatHistory(videoId: string): Promise<void> {
  await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/chat`, { method: 'DELETE' })
}

export async function processFile(
  file: File,
  language: string = 'auto',
): Promise<ProcessResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('language', language)
  const res = await fetch(`${BASE}/process/file`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Failed to upload file'))
  }
  return res.json()
}

export async function reextractSubtitles(videoId: string, language: string = 'auto', model?: string): Promise<void> {
  const res = await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/reextract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ language, ...(model ? { model } : {}) }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Failed to start re-extract'))
  }
}

export async function downloadDirect(
  videoUrl: string,
  format: 'mp4' | 'mp3' = 'mp4',
  quality: string = 'best',
): Promise<void> {
  const params = new URLSearchParams({ url: videoUrl, format, quality })
  const res = await fetch(`${BASE}/download/direct?${params}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Download failed'))
  }
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') || ''
  const nameMatch = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
  const filename = nameMatch ? nameMatch[1].replace(/['"]/g, '') : `video.${format}`
  const objUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objUrl
  a.download = filename
  a.click()
  URL.revokeObjectURL(objUrl)
}

export async function downloadVideo(
  videoId: string,
  format: 'mp4' | 'mp3' = 'mp4',
  quality: string = 'best',
): Promise<void> {
  const params = new URLSearchParams({ format, quality })
  const res = await fetch(`${BASE}/result/${encodeURIComponent(videoId)}/download?${params}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Download failed'))
  }
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') || ''
  const nameMatch = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
  const filename = nameMatch ? nameMatch[1].replace(/['"]/g, '') : `video.${format}`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export interface HealthResponse {
  backend: boolean
  ollama: boolean
}

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health`)
  if (!res.ok) throw new Error('Backend unreachable')
  return res.json()
}

export interface AppSettings {
  ollama_url: string | null
  ytdlp_path: string | null
  cookies_path: string | null
  force_map_reduce: string | null
  parallel_workers: string | null
  stt_engine: string | null
  stt_model: string | null
  stt_device: string | null
  stt_cache_path: string | null
  upload_auto_delete: string | null
  upload_auto_delete_mode: string | null
  upload_auto_delete_days: string | null
  chat_num_ctx: string | null
  download_default_format: string | null
  download_default_quality: string | null
}

export interface StageSettings {
  stage: string
  system_prompt: string | null
  user_prompt_template: string | null
  model: string | null
  is_default: boolean
}

export interface AllSettings {
  app: AppSettings
  cleanup: StageSettings
  summarization: StageSettings
  summarization_extract: StageSettings
  summarization_combine: StageSettings
  chat: StageSettings
}

export async function getSettings(): Promise<AllSettings> {
  const res = await fetch(`${BASE}/settings`)
  if (!res.ok) throw new Error('Failed to load settings')
  return res.json()
}

export async function saveAppSettings(data: Partial<AppSettings>): Promise<AppSettings> {
  const res = await fetch(`${BASE}/settings/app`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to save app settings')
  return res.json()
}

export async function saveSettings(
  stage: string,
  data: { system_prompt: string | null; user_prompt_template: string | null; model: string | null }
): Promise<StageSettings> {
  const res = await fetch(`${BASE}/settings/${stage}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to save settings')
  return res.json()
}

export async function resetSettings(stage: string): Promise<StageSettings> {
  const res = await fetch(`${BASE}/settings/${stage}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to reset settings')
  return res.json()
}

export async function getModels(): Promise<string[]> {
  const res = await fetch(`${BASE}/models`)
  if (!res.ok) return []
  const data = await res.json()
  return data.models ?? []
}

export interface SttModelInfo {
  name: string
  size_mb: number
  languages: number
  description: string
  speed: 'very fast' | 'fast' | 'medium' | 'slow'
  engine: 'faster_whisper' | 'qwen3_asr'
  downloaded: boolean
}

export interface SttDownloadStatus {
  status: 'not_started' | 'downloading' | 'done' | 'failed' | 'already_downloaded'
  downloaded_mb: number
  total_mb: number
  error?: string
}

export async function getSttModels(): Promise<SttModelInfo[]> {
  const res = await fetch(`${BASE}/stt/models`)
  if (!res.ok) return []
  const data = await res.json()
  return data.models ?? []
}

export async function downloadSttModel(name: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/stt/models/${encodeURIComponent(name)}/download`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to start download')
  return res.json()
}

export async function getSttModelDownloadStatus(name: string): Promise<SttDownloadStatus> {
  const res = await fetch(`${BASE}/stt/models/${encodeURIComponent(name)}/download/status`)
  if (!res.ok) throw new Error('Failed to get status')
  return res.json()
}

export async function deleteSttModel(name: string): Promise<void> {
  const res = await fetch(`${BASE}/stt/models/${encodeURIComponent(name)}`, { method: 'DELETE' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Failed to delete model'))
  }
}

// ---------------------------------------------------------------------------
// Benchmark
// ---------------------------------------------------------------------------

export interface BenchmarkRun {
  id: number
  video_id: string
  stage: string
  mode: string
  model: string
  input_chars: number
  output_text: string | null
  output_chars: number | null
  duration_seconds: number | null
  status: 'queued' | 'processing' | 'done' | 'failed'
  triggered_by?: 'main' | 'benchmark'
  created_at: string
}

export async function deleteBenchmarkRun(run_id: number): Promise<void> {
  const res = await fetch(`${BASE}/benchmark/run/${run_id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete run')
}

export async function startBenchmark(
  video_id: string,
  models: string[],
  mode_override?: string | null,
  stage: 'summary' | 'cleanup' = 'summary',
): Promise<{ run_ids: number[]; count: number }> {
  const res = await fetch(`${BASE}/benchmark/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_id, models, mode_override: mode_override ?? null, stage }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getBenchmarkRuns(video_id: string): Promise<BenchmarkRun[]> {
  const res = await fetch(`${BASE}/benchmark/${encodeURIComponent(video_id)}`)
  if (!res.ok) throw new Error('Failed to load benchmark runs')
  const data = await res.json()
  return data.runs ?? []
}

export interface BenchmarkGroup {
  video_id: string
  title: string | null
  total_runs: number
  models: string[]
  latest_run_at: string
}

export async function getAllBenchmarks(): Promise<BenchmarkGroup[]> {
  const res = await fetch(`${BASE}/benchmarks`)
  if (!res.ok) throw new Error('Failed to load benchmarks')
  const data = await res.json()
  return data.groups ?? []
}

// ---------------------------------------------------------------------------
// Queue (Epic 34)
// ---------------------------------------------------------------------------

export interface QueueItem {
  id: number
  url: string
  video_id: string | null
  db_video_id: string | null
  status: 'pending' | 'processing' | 'done' | 'failed' | 'skipped'
  pipeline_stages: string[]
  error_message: string | null
  added_at: string
  started_at: string | null
  finished_at: string | null
  sort_order: number
  progress: string | null
}

export interface QueueDuplicate {
  url: string | null
  video_id: string
  reason: 'processed' | 'in_queue'
}

export interface QueueAddResult {
  added: number
  ids: number[]
  invalid: string[]
  duplicates: string[]
  duplicate_details?: QueueDuplicate[]  // video id and reason per duplicate, from the server's own parser
}

export async function queueBulkAdd(
  urls: string[],
  pipeline_stages?: string[],
  force = false,
  language?: string,
): Promise<QueueAddResult> {
  const res = await fetchWithTimeout(`${BASE}/queue/bulk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls, pipeline_stages: pipeline_stages ?? null, force, language: language ?? null }),
  }, ADD_TIMEOUT_MS, ADD_TIMEOUT_HINT, true)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    if (res.status === 400 && body?.detail?.message === 'No valid YouTube URLs') {
      throw new InvalidLinkError(Array.isArray(body.detail.invalid) ? body.detail.invalid : [])
    }
    throw new Error(errorText(body, 'Failed to add to queue'))
  }
  return res.json()
}

/** Queue results that are already in History (also local files) by video_id; LLM stages only. */
export async function queueBulkAddByIds(
  video_ids: string[],
  pipeline_stages: string[],
): Promise<{ added: number; ids: number[]; invalid: string[]; duplicates: string[]; missing: string[] }> {
  const res = await fetchWithTimeout(`${BASE}/queue/bulk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_ids, pipeline_stages }),
  }, ADD_TIMEOUT_MS, ADD_TIMEOUT_HINT, true)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Failed to add to queue'))
  }
  return res.json()
}

export async function getQueue(): Promise<{ items: QueueItem[]; count: number }> {
  const res = await fetchWithTimeout(`${BASE}/queue`, {}, POLL_TIMEOUT_MS, POLL_TIMEOUT_HINT)
  if (!res.ok) throw new Error('Failed to load queue')
  return res.json()
}

export async function getQueueCounts(): Promise<{ pending: number; processing: number; active: number }> {
  const res = await fetch(`${BASE}/queue/counts`)
  if (!res.ok) return { pending: 0, processing: 0, active: 0 }
  return res.json()
}

export async function deleteQueueItem(id: number): Promise<void> {
  const res = await fetch(`${BASE}/queue/${id}`, { method: 'DELETE' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Failed to delete'))
  }
}

export async function clearQueuePending(): Promise<{ cleared: number }> {
  const res = await fetch(`${BASE}/queue/all`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to clear queue')
  return res.json()
}

export async function clearQueueFailed(): Promise<{ cleared: number }> {
  const res = await fetch(`${BASE}/queue/failed`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to clear failed items')
  return res.json()
}

export async function retryQueueItem(id: number): Promise<void> {
  const res = await fetch(`${BASE}/queue/${id}/retry`, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body, 'Failed to retry item'))
  }
}

export async function retryAllFailed(): Promise<{ retried: number }> {
  const res = await fetch(`${BASE}/queue/failed/retry`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to retry failed items')
  return res.json()
}

export interface StorageInfo {
  file_count: number
  total_mb: number
  auto_delete: boolean
  auto_delete_mode: 'immediate' | 'after_days'
  auto_delete_days: string
}

export async function getStorageInfo(): Promise<StorageInfo> {
  const res = await fetch(`${BASE}/settings/storage`)
  if (!res.ok) return { file_count: 0, total_mb: 0, auto_delete: false, auto_delete_mode: 'immediate', auto_delete_days: '7' }
  return res.json()
}

export async function clearUploads(): Promise<{ deleted: number; file_count: number; total_mb: number }> {
  const res = await fetch(`${BASE}/settings/storage/uploads`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to clear uploads')
  return res.json()
}

export async function getYtdlpVersion(): Promise<{
  version: string | null
  update_status: string
  new_version: string | null
  update_error: string | null
}> {
  const res = await fetch(`${BASE}/settings/ytdlp-version`)
  if (!res.ok) return { version: null, update_status: 'idle', new_version: null, update_error: null }
  return res.json()
}

export async function getYtdlpLatestVersion(): Promise<{ latest: string | null }> {
  const res = await fetch(`${BASE}/settings/ytdlp-latest`)
  if (!res.ok) return { latest: null }
  return res.json()
}

export async function updateYtdlp(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/settings/update-ytdlp`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to start update')
  return res.json()
}

// ---------------------------------------------------------------------------
// MCP Connect
// ---------------------------------------------------------------------------

export interface McpStatus {
  status: 'connected' | 'not_connected' | 'file_not_found' | 'docker_mode'
  config_paths: string[]
  entry_exists: boolean
  entry?: Record<string, unknown>
  manual_config?: string
}

export interface McpConnectResult {
  ok?: boolean
  planned?: boolean
  actions?: Array<{ path: string; action: string }>
  results?: Array<{ path: string; action: string; backup?: string; error?: string; verified?: boolean }>
  entry?: Record<string, unknown>
  error?: string
  message?: string
  manual_config?: string
}

export async function getMcpStatus(): Promise<McpStatus> {
  const res = await fetch(`${BASE}/mcp/status`)
  if (!res.ok) return { status: 'file_not_found', config_paths: [], entry_exists: false }
  return res.json()
}

export async function mcpConnect(confirm: boolean, replace_broken = false): Promise<McpConnectResult> {
  const res = await fetch(`${BASE}/mcp/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm, replace_broken }),
  })
  const data = await res.json()
  if (!res.ok) return { ok: false, error: data.detail?.error || data.detail || 'Unknown error', message: data.detail?.message }
  return data
}

export async function mcpDisconnect(): Promise<McpConnectResult> {
  const res = await fetch(`${BASE}/mcp/connect`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to disconnect')
  return res.json()
}
