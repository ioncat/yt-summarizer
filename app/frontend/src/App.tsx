import { Routes, Route, NavLink } from 'react-router-dom'
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

export default function App() {
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <NavLink to="/" className="logo">YT Summarizer</NavLink>
          <div className="sidebar-tagline">AI Productivity Suite</div>
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/" end className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}>+ New</NavLink>
          <NavLink to="/history" className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}>◷ History</NavLink>
          <NavLink to="/queue" className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}><QueueBadge /></NavLink>
          <NavLink to="/benchmarks" className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}>⚖ Benchmarks</NavLink>
        </nav>
        <div className="sidebar-bottom">
          <NavLink to="/settings" className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}>Settings ⚙</NavLink>
        </div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <StatusBar />
          <ThemeToggle />
        </header>
        <main className="main-content">
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
        </main>
      </div>
    </div>
  )
}
