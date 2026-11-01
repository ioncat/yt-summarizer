import { useEffect, useState } from 'react'
import { saveAppSettings, getStorageInfo, clearUploads, AppSettings, StorageInfo } from '../../api'
import { INPUT, SavedToast } from './primitives'

export function FileStoragePanel({ initial }: { initial: AppSettings }) {
  const [info, setInfo]             = useState<StorageInfo | null>(null)
  const [autoDelete, setAutoDelete] = useState(initial.upload_auto_delete === 'true')
  const [mode, setMode]             = useState<'immediate' | 'after_days'>(
    (initial.upload_auto_delete_mode as 'immediate' | 'after_days') || 'immediate',
  )
  const [days, setDays]             = useState(initial.upload_auto_delete_days ?? '7')
  const [saving, setSaving]         = useState(false)
  const [clearing, setClearing]     = useState(false)
  const [toast, setToast]           = useState('')

  function showToast(msg: string) { setToast(msg); setTimeout(() => setToast(''), 2500) }

  useEffect(() => {
    getStorageInfo().then(setInfo)
  }, [])

  async function handleSave() {
    setSaving(true)
    try {
      await saveAppSettings({
        upload_auto_delete: autoDelete ? 'true' : 'false',
        upload_auto_delete_mode: mode,
        upload_auto_delete_days: days,
      })
      showToast('Saved')
    } catch {
      showToast('Failed to save')
    } finally {
      setSaving(false)
    }
  }

  async function handleClear() {
    if (!window.confirm(`Delete all ${info?.file_count ?? 0} uploaded file(s)? This cannot be undone.`)) return
    setClearing(true)
    try {
      const result = await clearUploads()
      setInfo(prev => prev ? { ...prev, file_count: result.file_count, total_mb: result.total_mb } : prev)
      showToast(`Deleted ${result.deleted} file(s)`)
    } catch {
      showToast('Failed to clear uploads')
    } finally {
      setClearing(false)
    }
  }

  async function handleRefresh() {
    const fresh = await getStorageInfo()
    setInfo(fresh)
  }

  const totalGb = info ? (info.total_mb / 1024).toFixed(2) : '—'
  const totalLabel = info
    ? info.total_mb >= 1024
      ? `${totalGb} GB`
      : `${info.total_mb} MB`
    : '—'

  return (
    <div className="space-y-6">
      {/* Stats card */}
      <div className="p-5 bg-surface-container-low rounded-xl border border-outline-variant space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-label-sm text-on-surface-variant uppercase tracking-wider font-bold">Upload Storage</p>
          <button
            onClick={handleRefresh}
            className="text-[11px] text-primary hover:underline"
          >
            Refresh
          </button>
        </div>
        <div className="flex gap-6">
          <div>
            <p className="text-display-sm font-bold text-on-surface">
              {info ? info.file_count : '—'}
            </p>
            <p className="text-[11px] text-on-surface-variant mt-0.5">files</p>
          </div>
          <div>
            <p className="text-display-sm font-bold text-on-surface">{totalLabel}</p>
            <p className="text-[11px] text-on-surface-variant mt-0.5">used</p>
          </div>
        </div>
        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={handleClear}
            disabled={clearing || (info?.file_count ?? 0) === 0}
            className="px-4 py-2 text-label-md font-semibold rounded-lg bg-error-container text-on-error-container hover:opacity-90 active:scale-95 transition-all disabled:opacity-40"
          >
            {clearing ? 'Clearing…' : 'Clear all uploads'}
          </button>
          {info?.file_count === 0 && (
            <span className="text-[11px] text-on-surface-variant">No files to delete</span>
          )}
        </div>
      </div>

      {/* Auto-delete policy */}
      <div className="space-y-4">
        <p className="text-label-sm text-on-surface-variant uppercase tracking-wider font-bold">Auto-delete Policy</p>

        {/* Master toggle */}
        <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl border border-outline-variant">
          <div>
            <p className="text-label-md text-on-surface font-medium">Auto-delete uploaded files</p>
            <p className="text-[11px] text-on-surface-variant mt-0.5">
              {autoDelete
                ? mode === 'immediate' ? 'Files deleted right after transcription' : `Files deleted after ${days} day(s)`
                : 'Files kept indefinitely'}
            </p>
          </div>
          <button
            role="switch"
            aria-checked={autoDelete}
            onClick={() => setAutoDelete(v => !v)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${autoDelete ? 'bg-primary' : 'bg-surface-container-highest'}`}
          >
            <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${autoDelete ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>

        {/* Policy options — shown when auto-delete is ON */}
        {autoDelete && (
          <div className="ml-4 space-y-3">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="radio"
                name="delete-mode"
                value="immediate"
                checked={mode === 'immediate'}
                onChange={() => setMode('immediate')}
                className="accent-primary"
              />
              <div>
                <p className="text-label-md text-on-surface">Delete immediately after transcription</p>
                <p className="text-[11px] text-on-surface-variant">File removed as soon as transcription completes</p>
              </div>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="radio"
                name="delete-mode"
                value="after_days"
                checked={mode === 'after_days'}
                onChange={() => setMode('after_days')}
                className="accent-primary"
              />
              <div className="flex items-center gap-3">
                <div>
                  <p className="text-label-md text-on-surface">Keep for</p>
                </div>
                <input
                  type="number"
                  min={1}
                  max={365}
                  value={days}
                  onChange={e => setDays(e.target.value)}
                  disabled={mode !== 'after_days'}
                  className={`w-20 ${INPUT(false)} py-1.5 disabled:opacity-40`}
                />
                <p className="text-label-md text-on-surface">days, then delete on startup</p>
              </div>
            </label>
          </div>
        )}
      </div>

      {/* Save */}
      <div className="flex items-center gap-4 pt-1">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2.5 bg-primary text-on-primary text-label-md font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <SavedToast msg={toast} />
      </div>
    </div>
  )
}
