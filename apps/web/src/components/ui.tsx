import { useEffect, useRef, type ReactNode } from 'react'
import { ApiError, type Issue, type Lang } from '../lib/api'

export type T = (vi: string, en: string) => string
export const translate = (lang: Lang): T => (vi, en) => lang === 'vi' ? vi : en

export function confirmDiscard(container: ParentNode, t: T) {
  return !container.querySelector('form[data-dirty]') ||
    window.confirm(t('Bỏ thay đổi chưa lưu?', 'Discard unsaved changes?'))
}

export function Issues({ issues, t }: { issues: Issue[]; t: T }) {
  if (!issues.length) return null
  return <ul className="issues">{issues.map((issue, index) =>
    <li key={index} className={issue.severity?.toLowerCase()}>
      {issue.field && <strong>{issue.field} · </strong>}{issue.message}
      {issue.severity === 'Warning' && <span className="sr-only"> {t('Cảnh báo', 'Warning')}</span>}
    </li>)}</ul>
}

export function ErrorBox({ error, t, reload }: { error: unknown; t: T; reload?: () => void }) {
  if (!error) return null
  const stale = error instanceof ApiError && error.code === 'STALE_VERSION'
  const network = error instanceof TypeError
  return <div role="alert" className="notice error">
    <p>{network ? t('Không kết nối được máy chủ. Hãy thử lại.', 'Could not reach the server. Please retry.') :
      error instanceof Error ? error.message : String(error)}</p>
    {error instanceof ApiError && <Issues issues={error.issues} t={t} />}
    {stale && reload && <button type="button" onClick={reload}>{t('Tải lại dữ liệu', 'Reload data')}</button>}
  </div>
}

export function Modal({ title, onClose, children, busy = false, wide, t }: {
  title: string; onClose: () => void; children: ReactNode; busy?: boolean; wide?: boolean; t: T
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    dialog?.showModal()
    return () => dialog?.close()
  }, [])
  function close() {
    if (!busy && ref.current && confirmDiscard(ref.current, t)) onClose()
  }
  return <dialog ref={ref} className={wide ? 'wide-dialog' : undefined} onCancel={event => { event.preventDefault(); close() }}>
    <div className="section-head"><h2>{title}</h2>
      <button className="icon-button" onClick={close} disabled={busy} aria-label={t('Đóng', 'Close')}>×</button>
    </div>
    {children}
  </dialog>
}

const iconPaths = {
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5v5l3 2" /></>,
  list: <><rect x="5" y="4" width="14" height="16" rx="2" /><path d="M9 9h6M9 13h6M9 17h4" /></>,
  calendar: <><rect x="3.5" y="5" width="17" height="15" rx="2" /><path d="M7.5 3.5v4M16.5 3.5v4M3.5 10h17M8 14h2M14 14h2M8 17h2" /></>,
  history: <><path d="M3.5 11a8.5 8.5 0 1 1 2.2 7M3.5 6v5h5M12 7.5v5l3 1.5" /></>,
  moon: <path d="M20 15.25A8.5 8.5 0 0 1 8.75 4 8.5 8.5 0 1 0 20 15.25Z" />,
  sun: <><circle cx="12" cy="12" r="3.5" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4m10.6 10.6 1.4 1.4m0-13.4-1.4 1.4M6.7 17.3l-1.4 1.4" /></>,
  files: <><path d="M9 3h6l4 4v13a1 1 0 0 1-1 1H9a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" /><path d="M15 3v5h4M10 12h6M10 16h6" /></>,
  check: <><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12 2 2 5-5" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
} as const

export function Icon({ name }: { name: keyof typeof iconPaths }) {
  return <svg className="ui-icon" viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{iconPaths[name]}</svg>
}
