export const INPUT = (err?: boolean) =>
  `w-full bg-surface-container-low border ${err ? 'border-error' : 'border-outline-variant'} rounded-lg p-3 text-body-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all`

export const SELECT = (err?: boolean) =>
  `w-full bg-surface-container-low border ${err ? 'border-error' : 'border-outline-variant'} rounded-lg p-3 text-body-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all`

export const TEXTAREA = `w-full bg-surface-container-low border border-outline-variant rounded-lg p-3 text-body-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all resize-y`

export function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] text-on-surface-variant mt-1">{children}</p>
}

export function WarnBanner({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 p-4 bg-error-container/20 border border-error/30 rounded-lg">
      <span className="material-symbols-outlined text-error text-[18px] flex-shrink-0 mt-0.5">warning</span>
      <span className="text-body-sm text-on-error-container">{children}</span>
    </div>
  )
}

export function SavedToast({ msg }: { msg: string }) {
  if (!msg) return null
  return <span className="text-body-sm text-tertiary font-medium">{msg}</span>
}
