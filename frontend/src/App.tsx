import { Routes, Route, NavLink } from 'react-router-dom'
import HomePage from './pages/HomePage'
import ProcessingPage from './pages/ProcessingPage'
import ResultPage from './pages/ResultPage'
import HistoryPage from './pages/HistoryPage'

export default function App() {
  return (
    <>
      <nav>
        <NavLink to="/" className="logo">YT Summarizer</NavLink>
        <NavLink to="/">New</NavLink>
        <NavLink to="/history">History</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/processing/:taskId/:videoId" element={<ProcessingPage />} />
        <Route path="/result/:videoId" element={<ResultPage />} />
        <Route path="/history" element={<HistoryPage />} />
      </Routes>
    </>
  )
}
