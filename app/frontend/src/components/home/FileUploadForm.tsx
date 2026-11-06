import { useRef, useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { processFile } from '../../api'
import { LANGUAGES, selectBase } from './common'

const ACCEPTED_EXTENSIONS = '.mp4,.mkv,.avi,.mov,.webm,.mp3,.wav,.m4a,.ogg,.flac,.aac,.opus,.wma'

/** The "Local File" tab of the Home page: pick or drop a file, choose its language, upload it (it is queued, NS-11 stage 5). */
export function FileUploadForm() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [fileLanguage, setFileLanguage] = useState('auto')
  const [fileDragOver, setFileDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function handleFileSubmit(e: FormEvent) {
    e.preventDefault()
    if (!selectedFile) return
    setError('')
    setLoading(true)
    try {
      const res = await processFile(selectedFile, fileLanguage)
      navigate(`/processing/${res.task_id}/${res.video_id}?url=${encodeURIComponent('local://' + selectedFile.name)}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={handleFileSubmit}>
      <div
        className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer ${fileDragOver ? 'border-primary bg-primary/5' : 'border-outline-variant hover:border-primary/50'}`}
        onDragOver={e => { e.preventDefault(); setFileDragOver(true) }}
        onDragLeave={() => setFileDragOver(false)}
        onDrop={e => {
          e.preventDefault()
          setFileDragOver(false)
          const f = e.dataTransfer.files[0]
          if (f) setSelectedFile(f)
        }}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS}
          className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) setSelectedFile(f) }}
        />
        {selectedFile ? (
          <div className="flex flex-col items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[40px]">audio_file</span>
            <p className="text-body-md font-medium text-on-surface">{selectedFile.name}</p>
            <p className="text-label-sm text-secondary">{(selectedFile.size / (1024 * 1024)).toFixed(1)} MB</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 pointer-events-none">
            <span className="material-symbols-outlined text-secondary text-[40px]">upload_file</span>
            <p className="text-body-md text-on-surface-variant">Drop a file here, or click to browse</p>
            <p className="text-label-sm text-secondary">MP4, MKV, AVI, MOV, MP3, WAV, M4A, OGG, FLAC…</p>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-label-md text-on-surface-variant font-medium" htmlFor="file-lang">Language</label>
        <div className="relative">
          <select id="file-lang" className={selectBase} value={fileLanguage} onChange={e => setFileLanguage(e.target.value)}>
            {LANGUAGES.map(l => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
          <span className="material-symbols-outlined pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-secondary text-[20px]">expand_more</span>
        </div>
      </div>

      {error && (
        <div className="bg-error-container border border-error/30 rounded-lg px-4 py-3">
          <p className="text-body-sm text-on-error-container">{error}</p>
        </div>
      )}

      <button
        type="submit"
        disabled={loading || !selectedFile}
        className="bg-primary text-on-primary py-4 px-6 rounded-lg text-label-md font-bold transition-all hover:opacity-90 active:scale-[0.98] shadow-sm disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
      >
        {loading ? 'Uploading…' : 'Upload & Transcribe'}
      </button>
    </form>
  )
}
