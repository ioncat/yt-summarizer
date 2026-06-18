import { Routes, Route, NavLink, Link } from 'react-router-dom'
import HomePage from './pages/HomePage'
import ProcessingPage from './pages/ProcessingPage'
import ResultPage from './pages/ResultPage'
import HistoryPage from './pages/HistoryPage'
import SettingsPage from './pages/SettingsPage'
import BenchmarkPage from './pages/BenchmarkPage'
import BenchmarksIndexPage from './pages/BenchmarksIndexPage'
import QueuePage from './pages/QueuePage'
import StatusBar from './components/StatusBar'
import ThemeToggle from './components/ThemeToggle'
import QueueBadge from './components/QueueBadge'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 px-4 py-3 rounded-lg text-sm transition-all duration-150 active:scale-[0.98] ${
    isActive
      ? 'bg-primary-container text-on-primary-container font-medium'
      : 'text-secondary hover:bg-surface-container-high'
  }`

export default function App() {
  return (
    <div className="min-h-screen font-sans">
      {/* Sidebar */}
      <aside className="fixed left-0 top-0 h-full w-64 bg-surface-container-low border-r border-outline-variant flex flex-col p-4 z-40 hidden md:flex">
        <div className="mb-8 px-2">
          <Link to="/" className="block text-xl font-bold text-primary leading-tight">YT Summarizer</Link>
          <p className="text-sm text-secondary mt-1">AI Productivity Suite</p>
        </div>
        <nav className="flex-grow flex flex-col gap-1">
          <NavLink to="/" end className={navLinkClass}>
            <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>add_circle</span>
            New
          </NavLink>
          <NavLink to="/history" className={navLinkClass}>
            <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>history</span>
            History
          </NavLink>
          <NavLink to="/queue" className={navLinkClass}>
            <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>queue_play_next</span>
            <QueueBadge />
          </NavLink>
          <NavLink to="/benchmarks" className={navLinkClass}>
            <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>speed</span>
            Benchmarks
          </NavLink>
        </nav>
        <div className="mt-auto border-t border-outline-variant pt-4 flex flex-col gap-1">
          <NavLink to="/settings" className={navLinkClass}>
            <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>settings</span>
            Settings
          </NavLink>
        </div>
      </aside>

      {/* Main area */}
      <main className="md:ml-64 min-h-screen flex flex-col">
        {/* Topbar */}
        <header className="fixed top-0 left-0 right-0 md:left-64 z-30 h-16 bg-surface-container-lowest border-b border-outline-variant flex justify-between items-center px-6">
          <div className="hidden md:block">
            <StatusBar />
          </div>
          <div className="flex items-center gap-4 ml-auto">
            <ThemeToggle />
          </div>
        </header>

        {/* Page content */}
        <div className="flex-1 pt-16">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/processing/:taskId/:videoId" element={<ProcessingPage />} />
            <Route path="/result/:videoId" element={<ResultPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/benchmarks" element={<BenchmarksIndexPage />} />
            <Route path="/benchmark/:videoId" element={<BenchmarkPage />} />
            <Route path="/queue" element={<QueuePage />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}
