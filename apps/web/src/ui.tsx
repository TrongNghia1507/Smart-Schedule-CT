import { useEffect, useRef, type ReactNode } from 'react'
import { ApiError, type Issue, type Lang } from './api'

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

export function ClockIcon() {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5v5l3 2" /></svg>
}
