import { Routes, Route, NavLink } from 'react-router-dom'
import HomePage from './pages/HomePage'
import ProcessingPage from './pages/ProcessingPage'
import ResultPage from './pages/ResultPage'
import HistoryPage from './pages/HistoryPage'
import SettingsPage from './pages/SettingsPage'
import StatusBar from './components/StatusBar'

export default function App() {
  return (
    <>
      <nav>
        <div className="nav-left">
          <NavLink to="/" className="logo">YT Summarizer</NavLink>
        </div>
        <div className="nav-center">
          <NavLink to="/">+ New</NavLink>
          <NavLink to="/history">◷ History</NavLink>
          <NavLink to="/settings">Settings ⚙</NavLink>
        </div>
        <div className="nav-right">
          <StatusBar />
        </div>
      </nav>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/processing/:taskId/:videoId" element={<ProcessingPage />} />
        <Route path="/result/:videoId" element={<ResultPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </>
  )
}
