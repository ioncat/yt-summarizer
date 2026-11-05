import { Link, useLocation } from 'react-router-dom'

/** Shown for an address no page handles, e.g. /result/<a whole URL> (a video id never contains a slash). */
export default function NotFoundPage() {
  const { pathname } = useLocation()
  return (
    <div className="p-8 max-w-2xl mx-auto mt-12" data-testid="not-found">
      <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6">
        <h2 className="text-headline-md font-bold text-on-surface mb-2">Not found</h2>
        <p className="text-body-md text-secondary mb-1">Nothing is here:</p>
        <p className="text-body-sm font-mono break-all text-on-surface-variant mb-4">{pathname}</p>
        <div className="flex gap-3">
          <Link to="/history" className="px-4 py-2 bg-primary text-on-primary rounded-lg text-label-md font-semibold">History</Link>
          <Link to="/" className="px-4 py-2 bg-surface-container-high text-on-surface-variant rounded-lg text-label-md font-semibold">Home</Link>
        </div>
      </div>
    </div>
  )
}
