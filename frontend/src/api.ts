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
  cleanup_status: 'done' | 'unavailable'
  char_count: number | null
  created_at: string
}

export interface HistoryItem {
  video_id: string
  title: string | null
  author: string | null
  language: string | null
  created_at: string
}

export interface HistoryResponse {
  page: number
  items: HistoryItem[]
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
