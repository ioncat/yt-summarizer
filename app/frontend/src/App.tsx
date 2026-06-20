import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import HomePage from './pages/HomePage'
import ProcessingPage from './pages/ProcessingPage'
import ResultPage from './pages/ResultPage'
import HistoryPage from './pages/HistoryPage'
import SettingsPage from './pages/SettingsPage'
import BenchmarkPage from './pages/BenchmarkPage'
import BenchmarksIndexPage from './pages/BenchmarksIndexPage'
import QueuePage from './pages/QueuePage'
import { getHealth, getQueueCounts } from './api'
import { Theme, getInitialTheme, saveTheme } from './utils/theme'

type DotStatus = 'checking' | 'ok' | 'error'

export const BOXED_LAYOUT_EVENT = 'yt-boxed-layout-changed'
export const BOXED_LAYOUT_KEY   = 'yt_boxed_layout'

function SidebarNavItem({
  to, icon, label, badge, end,
}: {
  to: string; icon: string; label: string; badge?: number; end?: boolean
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        isActive
          ? 'flex items-center gap-3 px-4 py-3 bg-primary-container text-on-primary-container rounded-lg text-label-md font-medium transition-all active:scale-[0.98] duration-150'
          : 'flex items-center gap-3 px-4 py-3 text-secondary hover:bg-surface-container-high rounded-lg text-label-md font-medium transition-all duration-150'
      }
    >
      <span className="material-symbols-outlined text-[20px]">{icon}</span>
      <span className="flex-1">{label}</span>
      {badge !== undefined && badge > 0 && (
        <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-primary text-on-primary text-[10px] font-bold">
          {badge}
        </span>
      )}
    </NavLink>
  )
}

function SidebarContent({ queueActive }: { queueActive: number }) {
  return (
    <>
      <div className="mb-8 px-2">
        <h1 className="text-headline-lg font-bold text-primary">YT Summarizer</h1>
        <p className="text-label-md text-secondary mt-0.5">AI Productivity Suite</p>
      </div>
      <nav className="flex-grow flex flex-col gap-1">
        <SidebarNavItem to="/" icon="add_circle" label="New" end />
        <SidebarNavItem to="/history" icon="history" label="History" />
        <SidebarNavItem to="/queue" icon="queue_play_next" label="Queue" badge={queueActive} />
        <SidebarNavItem to="/benchmarks" icon="speed" label="Benchmarks" />
      </nav>
      <div className="mt-auto border-t border-outline-variant pt-4">
        <SidebarNavItem to="/settings" icon="settings" label="Settings" />
      </div>
    </>
  )
}

function HeaderContent({
  pageTitle, theme, setTheme, backendStatus, ollamaStatus,
}: {
  pageTitle: string
  theme: Theme
  setTheme: (fn: (t: Theme) => Theme) => void
  backendStatus: DotStatus
  ollamaStatus: DotStatus
}) {
  function dotColor(s: DotStatus) {
    return s === 'ok' ? 'bg-tertiary-container' : s === 'error' ? 'bg-error' : 'bg-surface-container-highest'
  }
  function dotTextColor(s: DotStatus) {
    return s === 'ok' ? 'text-tertiary' : s === 'error' ? 'text-error' : 'text-secondary'
  }

  return (
    <>
      <div className="flex items-center gap-6">
        <span className="md:hidden text-label-md font-semibold text-on-surface">{pageTitle}</span>
        <div className="hidden md:flex items-center gap-3">
          <span className="text-label-sm text-secondary font-medium">Systems Health:</span>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${dotColor(backendStatus)} ${backendStatus === 'ok' ? 'pulse-dot' : ''}`} />
            <span className={`text-label-sm font-bold ${dotTextColor(backendStatus)}`}>API</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${dotColor(ollamaStatus)} ${ollamaStatus === 'ok' ? 'pulse-dot' : ''}`} />
            <span className={`text-label-sm font-bold ${dotTextColor(ollamaStatus)}`}>Ollama</span>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setTheme(t => (t === 'light' ? 'dark' : 'light'))}
          className="p-2 text-secondary hover:bg-surface-container-high transition-colors rounded-full active:scale-95 duration-100"
          title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}
        >
          <span className="material-symbols-outlined text-[20px]">
            {theme === 'dark' ? 'light_mode' : 'dark_mode'}
          </span>
        </button>
      </div>
    </>
  )
}

export default function App() {
  const [theme, setTheme]               = useState<Theme>(getInitialTheme())
  const [backendStatus, setBackendStatus] = useState<DotStatus>('checking')
  const [ollamaStatus, setOllamaStatus] = useState<DotStatus>('checking')
  const [queueActive, setQueueActive]   = useState(0)
  const [boxedLayout, setBoxedLayout]   = useState(() => localStorage.getItem(BOXED_LAYOUT_KEY) === 'true')
  const location = useLocation()

  useEffect(() => { saveTheme(theme) }, [theme])

  // Sync boxed layout toggle from SettingsPage
  useEffect(() => {
    const handler = (e: Event) => setBoxedLayout((e as CustomEvent<boolean>).detail)
    window.addEventListener(BOXED_LAYOUT_EVENT, handler)
    return () => window.removeEventListener(BOXED_LAYOUT_EVENT, handler)
  }, [])

  useEffect(() => {
    function checkHealth() {
      getHealth()
        .then(h => { setBackendStatus(h.backend ? 'ok' : 'error'); setOllamaStatus(h.ollama ? 'ok' : 'error') })
        .catch(() => { setBackendStatus('error'); setOllamaStatus('error') })
    }
    checkHealth()
    const id = setInterval(checkHealth, 15_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    let mounted = true
    function checkQueue() {
      getQueueCounts().then(c => { if (mounted) setQueueActive(c.active) }).catch(() => {})
    }
    checkQueue()
    const id = setInterval(checkQueue, 4_000)
    return () => { mounted = false; clearInterval(id) }
  }, [])

  const pageTitle = (() => {
    if (location.pathname === '/') return 'New Summary'
    if (location.pathname.startsWith('/history'))   return 'History'
    if (location.pathname.startsWith('/queue'))     return 'Processing Queue'
    if (location.pathname.startsWith('/settings'))  return 'Settings'
    if (location.pathname.startsWith('/benchmark')) return 'Benchmarks'
    if (location.pathname.startsWith('/result'))    return 'Result'
    if (location.pathname.startsWith('/processing')) return 'Processing'
    return 'YT Summarizer'
  })()

  const routes = (
    <Routes>
      <Route path="/"                             element={<HomePage />} />
      <Route path="/processing/:taskId/:videoId"  element={<ProcessingPage />} />
      <Route path="/result/:videoId"              element={<ResultPage />} />
      <Route path="/history"                      element={<HistoryPage />} />
      <Route path="/settings"                     element={<SettingsPage />} />
      <Route path="/benchmarks"                   element={<BenchmarksIndexPage />} />
      <Route path="/benchmark/:videoId"           element={<BenchmarkPage />} />
      <Route path="/queue"                        element={<QueuePage />} />
    </Routes>
  )

  const headerProps = { pageTitle, theme, setTheme, backendStatus, ollamaStatus }

  // ── Boxed layout ──────────────────────────────────────────────────────────
  if (boxedLayout) {
    return (
      <div
        className="min-h-screen p-4 lg:p-8 flex items-start justify-center transition-colors"
        style={{ background: theme === 'dark'
          ? 'linear-gradient(to bottom right, #3f3f46, #27272a)'
          : 'linear-gradient(to bottom right, #e2e8f0, #cbd5e1)' }}
      >
        <div
          className="w-full max-w-[1600px] rounded-[32px] shadow-2xl overflow-hidden border border-outline-variant bg-surface flex"
          style={{ height: 'calc(100vh - 2rem)' }}
        >
          {/* Sidebar — inline, not fixed */}
          <aside className="w-64 flex-shrink-0 hidden md:flex flex-col p-4 bg-surface-container-low border-r border-outline-variant overflow-y-auto">
            <SidebarContent queueActive={queueActive} />
          </aside>

          {/* Right column: header + scrollable content */}
          <div className="flex-1 flex flex-col overflow-hidden min-w-0">
            <header className="h-16 flex-shrink-0 bg-surface-container-lowest border-b border-outline-variant flex items-center justify-between px-6 z-10">
              <HeaderContent {...headerProps} />
            </header>
            <main className="flex-1 overflow-y-auto">
              {routes}
            </main>
          </div>
        </div>
      </div>
    )
  }

  // ── Normal (full-screen) layout ───────────────────────────────────────────
  return (
    <div className="min-h-screen bg-background text-on-background">
      <aside className="fixed left-0 top-0 h-full w-64 bg-surface-container-low border-r border-outline-variant flex flex-col p-4 z-40 hidden md:flex">
        <SidebarContent queueActive={queueActive} />
      </aside>

      <main className="md:ml-64 min-h-screen flex flex-col">
        <header className="fixed top-0 left-0 right-0 md:left-64 z-30 h-16 bg-surface-container-lowest border-b border-outline-variant flex items-center justify-between px-6">
          <HeaderContent {...headerProps} />
        </header>
        <div className="mt-16 flex-grow">
          {routes}
        </div>
      </main>
    </div>
  )
}
