const BASE = '/api'

export interface ProcessResponse {
  task_id: string
  video_id: string
}

export interface StatusResponse {
  task_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
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
  created_at: string
  cleanup_finished_at: string | null
  summary_finished_at: string | null
  chat_history: Array<{ role: string; content: string }> | null
  mindmap_text: string | null
  mindmap_status: 'processing' | 'done' | 'failed' | null
}

export interface HistoryItem {
  video_id: string
  title: string | null
  author: string | null
  language: string | null
  char_count: number | null
  has_chapters?: boolean
  has_cleaned?: boolean
  has_summary?: boolean
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
  const res = await fetch(`${BASE}/status/${taskId}`)
  if (!res.ok) throw new Error('Status not found')
  return res.json()
}

export async function getResult(videoId: string): Promise<ResultResponse> {
  const res = await fetch(`${BASE}/result/${videoId}`)
  if (!res.ok) throw new Error('Result not found')
  return res.json()
}

export async function getHistory(page = 1): Promise<HistoryResponse> {
  const res = await fetch(`${BASE}/history?page=${page}`)
  if (!res.ok) throw new Error('Failed to load history')
  return res.json()
}

export async function deleteResult(videoId: string): Promise<void> {
  const res = await fetch(`${BASE}/result/${videoId}`, { method: 'DELETE' })
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
  await fetch(`${BASE}/result/${videoId}/cleanup`, { method: 'DELETE' })
}

export async function startSummary(videoId: string): Promise<void> {
  const res = await fetch(`${BASE}/result/${videoId}/summary`, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || 'Failed to start summarization')
  }
}

export async function cancelSummary(videoId: string): Promise<void> {
  await fetch(`${BASE}/result/${videoId}/summary`, { method: 'DELETE' })
}

export async function startMindmap(videoId: string, force = false): Promise<void> {
  const url = force
    ? `${BASE}/result/${videoId}/mindmap?force=true`
    : `${BASE}/result/${videoId}/mindmap`
  const res = await fetch(url, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || 'Failed to start mindmap generation')
  }
}

export async function cancelMindmap(videoId: string): Promise<void> {
  await fetch(`${BASE}/result/${videoId}/mindmap`, { method: 'DELETE' })
}

export async function startCleanup(videoId: string): Promise<void> {
  const res = await fetch(`${BASE}/result/${videoId}/cleanup`, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || 'Failed to start cleanup')
  }
}

export async function saveChatHistory(
  videoId: string,
  messages: Array<{ role: string; content: string }>
): Promise<void> {
  await fetch(`${BASE}/result/${videoId}/chat`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })
}

export async function clearChatHistory(videoId: string): Promise<void> {
  await fetch(`${BASE}/result/${videoId}/chat`, { method: 'DELETE' })
}

export async function reextractSubtitles(videoId: string, language: string = 'auto'): Promise<void> {
  const res = await fetch(`${BASE}/result/${videoId}/reextract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ language }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || 'Failed to start re-extract')
  }
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
  const res = await fetch(`${BASE}/benchmark/${video_id}`)
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
}

export async function queueBulkAdd(
  urls: string[],
  pipeline_stages?: string[],
): Promise<{ added: number; ids: number[]; invalid: string[]; duplicates: string[] }> {
  const res = await fetch(`${BASE}/queue/bulk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls, pipeline_stages: pipeline_stages ?? null }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail?.message || body.detail || 'Failed to add to queue')
  }
  return res.json()
}

export async function getQueue(): Promise<{ items: QueueItem[]; count: number }> {
  const res = await fetch(`${BASE}/queue`)
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
    throw new Error(body.detail || 'Failed to delete')
  }
}

export async function clearQueuePending(): Promise<{ cleared: number }> {
  const res = await fetch(`${BASE}/queue/all`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to clear queue')
  return res.json()
}
