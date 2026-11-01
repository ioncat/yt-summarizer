import { useEffect, useState } from 'react'
import { getMcpStatus, mcpConnect, mcpDisconnect, McpStatus } from '../../api'

export function ConnectionsPanel() {
  const [status, setStatus] = useState<McpStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  function flash(m: string, isError = false) {
    if (isError) { setError(m); setMsg('') }
    else { setMsg(m); setError('') }
    setTimeout(() => { setMsg(''); setError('') }, 4000)
  }

  async function reload() {
    setLoading(true)
    try { setStatus(await getMcpStatus()) }
    finally { setLoading(false) }
  }

  useEffect(() => { reload() }, [])

  async function handleConnect() {
    setBusy(true)
    try {
      const result = await mcpConnect(true)
      if (result.error) {
        const errMap: Record<string, string> = {
          desktop_running: 'Close Claude Desktop completely (including the tray), then try again.',
          desktop_status_unknown: 'Could not check if Claude Desktop is running. Close it first, then try again.',
          no_config_dir: 'Claude Desktop config directory not found. Install Claude Desktop and open it once.',
          broken_config: 'Config file has invalid JSON.',
        }
        flash(errMap[result.error] || result.message || result.error, true)
      } else {
        flash(result.message || 'Connected! Restart Claude Desktop.')
        await reload()
      }
    } finally { setBusy(false) }
  }

  async function handleDisconnect() {
    setBusy(true)
    try {
      const result = await mcpDisconnect()
      flash(result.message || 'Disconnected.')
      await reload()
    } catch { flash('Failed to disconnect.', true) }
    finally { setBusy(false) }
  }

  function handleCopy(text: string) {
    navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000) })
  }

  if (loading) {
    return <div className="text-body-sm text-on-surface-variant animate-pulse">Checking status…</div>
  }

  const s = status!

  return (
    <div className="space-y-5">
      <p className="text-body-sm text-on-surface-variant">
        Connect Claude Desktop so it can work with your videos directly in chat using MCP tools.
      </p>

      {/* Status card */}
      <div className="bg-surface-container rounded-2xl p-5 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-label-lg text-on-surface font-medium">Claude Desktop</p>
            <p className="text-body-sm text-on-surface-variant mt-0.5">
              {s.status === 'connected' && 'Adds YT Summarizer tools to Claude Desktop via MCP'}
              {s.status === 'not_connected' && 'Not connected — click Connect to set up'}
              {s.status === 'file_not_found' && 'Claude Desktop config directory not found'}
              {s.status === 'docker_mode' && 'Running in Docker — manual setup required'}
            </p>
          </div>

          {/* Status badge */}
          {s.status === 'connected' ? (
            <span className="flex items-center gap-1.5 px-3 py-1 bg-tertiary-container/40 text-tertiary rounded-full text-label-sm font-medium shrink-0">
              <span className="w-2 h-2 rounded-full bg-tertiary inline-block" />
              Connected
            </span>
          ) : s.status === 'not_connected' ? (
            <span className="flex items-center gap-1.5 px-3 py-1 bg-surface-container-highest text-on-surface-variant rounded-full text-label-sm shrink-0">
              <span className="w-2 h-2 rounded-full bg-outline inline-block" />
              Not connected
            </span>
          ) : null}
        </div>

        {/* Config path when connected */}
        {s.status === 'connected' && s.config_paths.length > 0 && (
          <p className="text-[11px] text-on-surface-variant font-mono truncate">
            {s.config_paths[0]}
          </p>
        )}

        {/* Docker mode: show manual config */}
        {s.status === 'docker_mode' && s.manual_config && (
          <div className="space-y-2">
            <p className="text-body-sm text-on-surface-variant">
              Add this to <code className="text-label-sm bg-surface-container-highest px-1 py-0.5 rounded">claude_desktop_config.json</code>:
            </p>
            <div className="relative">
              <pre className="bg-surface-container-highest rounded-lg p-3 text-[11px] font-mono overflow-x-auto text-on-surface whitespace-pre">
                {s.manual_config}
              </pre>
              <button
                onClick={() => handleCopy(s.manual_config!)}
                className="absolute top-2 right-2 flex items-center gap-1 px-2 py-1 rounded bg-primary/10 hover:bg-primary/20 text-primary text-[11px] font-medium transition-colors"
              >
                <span className="material-symbols-outlined text-[14px]">{copied ? 'check' : 'content_copy'}</span>
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>
        )}

        {/* File not found: show expected path */}
        {s.status === 'file_not_found' && (
          <p className="text-body-sm text-on-surface-variant">
            Install <a href="https://claude.ai/download" target="_blank" rel="noreferrer" className="text-primary underline">Claude Desktop</a> and open it once to create the config directory.
          </p>
        )}

        {/* Action buttons */}
        {(s.status === 'connected' || s.status === 'not_connected') && (
          <div className="flex items-center gap-3 pt-1">
            {s.status === 'not_connected' && (
              <button
                onClick={handleConnect}
                disabled={busy}
                className="flex items-center gap-2 px-4 py-2 bg-primary text-on-primary rounded-xl text-label-md font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                <span className="material-symbols-outlined text-[18px]">link</span>
                {busy ? 'Connecting…' : 'Connect Claude Desktop'}
              </button>
            )}
            {s.status === 'connected' && (
              <>
                <button
                  onClick={handleConnect}
                  disabled={busy}
                  className="flex items-center gap-2 px-4 py-2 bg-surface-container-highest text-on-surface rounded-xl text-label-md font-medium hover:bg-surface-container hover:text-primary border border-outline-variant disabled:opacity-50 transition-colors"
                >
                  <span className="material-symbols-outlined text-[18px]">refresh</span>
                  {busy ? 'Updating…' : 'Reconnect'}
                </button>
                <button
                  onClick={handleDisconnect}
                  disabled={busy}
                  className="flex items-center gap-2 px-4 py-2 text-error rounded-xl text-label-md font-medium hover:bg-error-container/20 disabled:opacity-50 transition-colors"
                >
                  <span className="material-symbols-outlined text-[18px]">link_off</span>
                  {busy ? 'Disconnecting…' : 'Disconnect'}
                </button>
              </>
            )}
          </div>
        )}

        {/* Feedback messages */}
        {msg && <p className="text-body-sm text-tertiary">{msg}</p>}
        {error && <p className="text-body-sm text-error">{error}</p>}
      </div>

      {/* Info note */}
      {(s.status === 'connected' || s.status === 'not_connected') && (
        <p className="text-[11px] text-on-surface-variant">
          After connecting, restart Claude Desktop. The MCP server starts on demand — your YT Summarizer backend must be running for the tools to work.
        </p>
      )}
    </div>
  )
}
