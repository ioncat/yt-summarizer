import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import SettingsPage from '../pages/SettingsPage'
import * as api from '../api'

vi.mock('../App', () => ({
  BOXED_LAYOUT_EVENT: 'boxed-layout-change',
  BOXED_LAYOUT_KEY: 'boxed-layout',
}))

const stage = (name: string, model: string | null = null) => ({
  stage: name, system_prompt: 'sys', user_prompt_template: 'tpl {text}', model, is_default: true,
})

const appSettings = {
  ollama_url: 'http://localhost:11434',
  ytdlp_path: null,
  cookies_path: '../data/cookies.txt',
  force_map_reduce: 'false',
  parallel_workers: '2',
  stt_engine: null,
  stt_model: 'base',
  stt_device: 'auto',
  stt_cache_path: null,
  upload_auto_delete: 'false',
  upload_auto_delete_mode: 'immediate',
  upload_auto_delete_days: '7',
  chat_num_ctx: '32768',
  llm_max_num_ctx: '32768',
  download_default_format: 'mp4',
  download_default_quality: 'best',
}

vi.mock('../api', () => ({
  getSettings: vi.fn(),
  saveAppSettings: vi.fn(),
  saveSettings: vi.fn(),
  resetSettings: vi.fn(),
  getModels: vi.fn(),
  getSttModels: vi.fn(),
  downloadSttModel: vi.fn(),
  getSttModelDownloadStatus: vi.fn(),
  deleteSttModel: vi.fn(),
  getYtdlpVersion: vi.fn(),
  getYtdlpLatestVersion: vi.fn(),
  updateYtdlp: vi.fn(),
  getStorageInfo: vi.fn(),
  clearUploads: vi.fn(),
  getMcpStatus: vi.fn(),
  mcpConnect: vi.fn(),
  mcpDisconnect: vi.fn(),
}))

const m = vi.mocked(api)

async function renderPage() {
  render(<SettingsPage />)
  await screen.findByText('Configure the application. All settings are stored in the database.')
}

async function openTab(label: string) {
  fireEvent.click(screen.getByRole('button', { name: label }))
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    m.getSettings.mockResolvedValue({
      app: appSettings,
      cleanup: stage('cleanup', 'llama3'),
      summarization: stage('summarization', 'llama3'),
      summarization_extract: stage('summarization_extract'),
      summarization_combine: stage('summarization_combine'),
      chat: stage('chat'),
    } as never)
    m.getModels.mockResolvedValue(['llama3', 'qwen3'])
    m.getSttModels.mockResolvedValue([
      { name: 'base', engine: 'faster-whisper', description: 'Base model', size_mb: 150, languages: 99, speed: 'fast', downloaded: true },
      { name: 'large-v3', engine: 'faster-whisper', description: 'Large model', size_mb: 3000, languages: 99, speed: 'slow', downloaded: false },
    ] as never)
    m.getYtdlpVersion.mockResolvedValue({ version: '2025.1.1', update_status: 'idle', new_version: null, update_error: null } as never)
    m.getYtdlpLatestVersion.mockResolvedValue({ latest: '2025.1.1' } as never)
    m.getStorageInfo.mockResolvedValue({ file_count: 3, total_mb: 12.5, auto_delete: false, auto_delete_mode: 'immediate', auto_delete_days: '7' } as never)
    m.getMcpStatus.mockResolvedValue({ status: 'not_connected', config_paths: [], manual_config: null } as never)
    m.saveAppSettings.mockResolvedValue(appSettings as never)
    m.saveSettings.mockResolvedValue(stage('cleanup', 'qwen3') as never)
    m.mcpConnect.mockResolvedValue({ message: 'Connected!' } as never)
  })

  it('shows all tabs in order', async () => {
    await renderPage()
    const labels = ['General', 'AI Cleanup', 'Summarization', 'Chat', 'Speech-to-Text', 'File Storage', 'Connections']
    const tabs = screen.getAllByRole('button').map(b => b.textContent).filter(t => labels.includes(t ?? ''))
    expect(tabs).toEqual(labels)
  })

  it('General tab: controls present and Save calls saveAppSettings', async () => {
    await renderPage()
    expect(screen.getByDisplayValue('http://localhost:11434')).toBeTruthy()
    expect(screen.getByText('Chat context window (minimum)')).toBeTruthy()
    expect(screen.getByLabelText('Context limit for cleanup, summary and mind map')).toBeTruthy()
    expect(screen.getByText('Parallel workers')).toBeTruthy()
    expect(screen.getByText('Download defaults')).toBeTruthy()
    expect(screen.getByText('Boxed layout (floating UI)')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(m.saveAppSettings).toHaveBeenCalledTimes(1))
    expect(m.saveAppSettings.mock.calls[0][0]).toMatchObject({
      ollama_url: 'http://localhost:11434',
      parallel_workers: '2',
      chat_num_ctx: '32768',
    })
  })

  it('General tab: the context limit of the LLM steps is a field, saved with the other settings (NS-26)', async () => {
    await renderPage()
    const field = screen.getByLabelText('Context limit for cleanup, summary and mind map') as HTMLSelectElement
    expect(field.value).toBe('32768')
    expect(Array.from(field.options).map(o => o.value)).toEqual(['4096', '8192', '16384', '32768', '65536'])   // the server's range
    fireEvent.change(field, { target: { value: '65536' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(m.saveAppSettings).toHaveBeenCalledTimes(1))
    expect(m.saveAppSettings.mock.calls[0][0]).toMatchObject({ llm_max_num_ctx: '65536', chat_num_ctx: '32768' })
  })

  it('AI Cleanup tab: model change and Save call saveSettings', async () => {
    await renderPage()
    await openTab('AI Cleanup')
    expect(screen.getByText('System prompt')).toBeTruthy()
    expect(screen.getByText('User prompt template')).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'qwen3' } })
    await waitFor(() => expect(m.saveSettings).toHaveBeenCalledTimes(1))
    expect(m.saveSettings.mock.calls[0][0]).toBe('cleanup')
    expect(m.saveSettings.mock.calls[0][1]).toMatchObject({ model: 'qwen3' })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(m.saveSettings).toHaveBeenCalledTimes(2))
  })

  it('Summarization tab: force map-reduce toggle, sub-tabs and steps', async () => {
    await renderPage()
    await openTab('Summarization')
    fireEvent.click(screen.getByLabelText('Force Map-Reduce mode'))
    await waitFor(() => expect(m.saveAppSettings).toHaveBeenCalledWith({ force_map_reduce: 'true' }))
    expect(screen.getByRole('button', { name: 'Single Pass' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Map-Reduce' }))
    expect(screen.getByRole('button', { name: 'Step 1 — Extract (per chunk)' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Step 2 — Combine (all chunks)' }))
    expect(screen.getByText('User prompt template')).toBeTruthy()
  })

  it('Chat tab: model change calls saveSettings with chat stage', async () => {
    await renderPage()
    await openTab('Chat')
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'qwen3' } })
    await waitFor(() => expect(m.saveSettings).toHaveBeenCalled())
    expect(m.saveSettings.mock.calls[0][0]).toBe('chat')
  })

  it('Speech-to-Text tab: lists models and device change saves', async () => {
    await renderPage()
    await openTab('Speech-to-Text')
    expect(screen.getByText('large-v3')).toBeTruthy()
    expect(screen.getByText('Active')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Download/ })).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'cpu' } })
    await waitFor(() => expect(m.saveAppSettings).toHaveBeenCalledWith({ stt_device: 'cpu' }))
  })

  it('File Storage tab: stats shown and Save calls saveAppSettings', async () => {
    await renderPage()
    await openTab('File Storage')
    await screen.findByText('12.5 MB')
    expect(screen.getByRole('button', { name: 'Clear all uploads' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(m.saveAppSettings).toHaveBeenCalledWith({
      upload_auto_delete: 'false',
      upload_auto_delete_mode: 'immediate',
      upload_auto_delete_days: '7',
    }))
  })

  it('Connections tab: Connect calls mcpConnect(true)', async () => {
    await renderPage()
    await openTab('Connections')
    fireEvent.click(await screen.findByRole('button', { name: /Connect Claude Desktop/ }))
    await waitFor(() => expect(m.mcpConnect).toHaveBeenCalledWith(true))
  })
})
