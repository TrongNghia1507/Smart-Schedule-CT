import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { anonymous, ApiError, createClient, type Draft, type Lang, type Session } from './api'
import { AuthPage } from './AuthPage'
import { DraftPage, type ChangeDraft } from './DraftPage'
import { ClockIcon, confirmDiscard, ErrorBox, translate } from './ui'
import './styles.css'

type Theme = 'light' | 'dark'
type Page = 'input' | 'calendar' | 'history'
const base = '/app/'
const PlannerPage = lazy(() => import('./PlannerPage').then(module => ({ default: module.PlannerPage })))
const HistoryPage = lazy(() => import('./HistoryPage').then(module => ({ default: module.HistoryPage })))
const AdminPage = lazy(() => import('./AdminPage').then(module => ({ default: module.AdminPage })))

function initialPreference<T extends string>(key: string, values: T[], fallback: T): T {
  const query = new URLSearchParams(location.search).get(key)
  const saved = localStorage.getItem(key)
  return values.find(value => value === query) ?? values.find(value => value === saved) ?? fallback
}

function initialPage(): Page {
  const section = location.pathname.slice(base.length).split('/')[0]
  return section === 'calendar' || section === 'history' ? section : 'input'
}

function App() {
  const [lang, setLang] = useState(() => initialPreference<Lang>('lang', ['vi', 'en'], 'vi'))
  const [theme, setTheme] = useState(() => initialPreference<Theme>('theme', ['light', 'dark'], 'light'))
  const [session, setSession] = useState<Session | null | undefined>(undefined)
  const [error, setError] = useState<unknown>(null)
  const [authNotice, setAuthNotice] = useState(false)
  const [page, setPage] = useState(initialPage)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [loadVersion, setLoadVersion] = useState(0)
  const t = translate(lang)

  const endSession = useCallback(() => { setSession(null); setDraft(null); setError(null) }, [])
  const client = useMemo(() => createClient(session?.csrf, endSession), [session?.csrf, endSession])

  useEffect(() => {
    document.documentElement.lang = lang
    document.documentElement.dataset.theme = theme
    localStorage.setItem('lang', lang)
    localStorage.setItem('theme', theme)
  }, [lang, theme])

  useEffect(() => {
    let active = true
    anonymous.get<Session>('/auth/me').then(value => { if (active) setSession(value) })
      .catch(failure => {
        if (!active) return
        if (failure instanceof ApiError && failure.status === 401) setSession(null)
        else setError(failure)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!session || session.user.role === 'admin') return
    let active = true
    client.get<Draft>('/draft').then(value => { if (active) setDraft(value) })
      .catch(failure => { if (active) setError(failure) })
    return () => { active = false }
  }, [client, session, loadVersion])

  useEffect(() => {
    const pop = () => {
      const nextPage = initialPage()
      if (nextPage === page || confirmDiscard(document, translate(lang))) setPage(nextPage)
      else history.pushState(null, '', base + (page === 'input' ? '' : page) + location.search)
    }
    const unload = (event: BeforeUnloadEvent) => {
      if (document.querySelector('form[data-dirty]')) event.preventDefault()
    }
    window.addEventListener('popstate', pop)
    window.addEventListener('beforeunload', unload)
    return () => {
      window.removeEventListener('popstate', pop)
      window.removeEventListener('beforeunload', unload)
    }
  }, [page, lang])

  function navigate(next: Page, check = true) {
    if (next === page || (check && !confirmDiscard(document, t))) return
    history.pushState(null, '', base + (next === 'input' ? '' : next) + location.search)
    setPage(next)
    window.scrollTo(0, 0)
  }

  function preference(key: 'lang' | 'theme', value: string) {
    const url = new URL(location.href)
    url.searchParams.set(key, value)
    history.replaceState(null, '', url)
    if (key === 'lang') setLang(value as Lang)
    else setTheme(value as Theme)
  }

  function reload() {
    setError(null)
    setLoadVersion(value => value + 1)
  }

  const change: ChangeDraft = async command => {
    const next = await client.send<Draft>('/draft/changes', { ...command, expected_revision: draft?.revision })
    setDraft(next)
    return next
  }

  async function signOut() {
    if (!confirmDiscard(document, t)) return
    try {
      await client.send('/auth/logout')
      endSession()
      setAuthNotice(false)
    } catch (failure) {
      if (!(failure instanceof ApiError && failure.status === 401)) setError(failure)
    }
  }

  const planner = session?.user.role === 'user'
  const tabs: [Page, string][] = [['input', t('Nhập dữ liệu', 'Input')], ['calendar', t('Lịch tuần', 'Calendar')],
    ['history', t('Lịch sử', 'History')]]
  return <div onChange={event => {
    const form = (event.target as HTMLElement).closest<HTMLFormElement>('form[data-track]')
    if (form) form.dataset.dirty = 'true'
  }}>
    <header className="topbar">
      <div className="topbar-inner">
        <a href={base} className="brand" onClick={event => {
          if (planner) { event.preventDefault(); navigate('input') }
        }}><span className="brand-mark"><ClockIcon /></span>Smart Schedule CT</a>
        {planner && <nav aria-label={t('Điều hướng chính', 'Main navigation')}>{tabs.map(([id, label]) =>
          <a key={id} href={base + (id === 'input' ? '' : id) + location.search} aria-current={page === id ? 'page' : undefined}
            onClick={event => {
              if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
              event.preventDefault()
              navigate(id)
            }}>{label}</a>)}</nav>}
        <div className="account">
          <label className="compact-label"><span className="sr-only">{t('Ngôn ngữ', 'Language')}</span>
            <select aria-label={t('Ngôn ngữ', 'Language')} value={lang} onChange={event => preference('lang', event.target.value)}>
              <option value="vi">VI</option><option value="en">EN</option>
            </select></label>
          <button className="icon-button" title={t('Đổi giao diện sáng / tối', 'Toggle light / dark theme')}
            aria-label={t('Đổi giao diện sáng / tối', 'Toggle light / dark theme')}
            onClick={() => preference('theme', theme === 'light' ? 'dark' : 'light')}>
            <span aria-hidden="true">{theme === 'light' ? '☾' : '☀'}</span>
          </button>
          {session && <><span className="account-name" title={session.user.full_name}>{session.user.full_name}</span>
            <button onClick={() => void signOut()}>{t('Đăng xuất', 'Sign out')}</button></>}
        </div>
      </div>
    </header>
    {session === null ? <>
      {authNotice && <div className="auth-message notice" role="status">{t('Đã đổi mật khẩu. Hãy đăng nhập lại.',
        'Password changed. Sign in again.')}</div>}
      <AuthPage t={t} onSession={value => { setAuthNotice(false); setSession(value) }} />
    </> : <main className="workspace">
      <ErrorBox error={error} t={t} reload={reload} />
      {session === undefined && error ? <button onClick={() => location.reload()}>{t('Thử lại', 'Retry')}</button> : null}
      <Suspense fallback={<p role="status">{t('Đang tải…', 'Loading…')}</p>}>
        {session?.user.role === 'admin' && <AdminPage client={client} lang={lang} t={t}
          onChanged={() => { endSession(); setAuthNotice(true) }} />}
        {planner && draft && page === 'calendar' && <PlannerPage draft={draft} client={client} change={change}
          reload={reload} toInput={() => navigate('input')} lang={lang} t={t} />}
        {planner && draft && page === 'history' && <HistoryPage draft={draft} client={client}
          onRestore={value => { setDraft(value); navigate('input', false) }} reload={reload} lang={lang} t={t} />}
      </Suspense>
      {planner && draft && page === 'input' && <DraftPage draft={draft} client={client} change={change} adopt={setDraft}
        reload={reload} advance={() => navigate('calendar')} t={t} />}
      {(!session || (planner && !draft)) && (error ? session && <button onClick={reload}>{t('Thử lại', 'Retry')}</button> :
        <p role="status">{t('Đang tải…', 'Loading…')}</p>)}
    </main>}
  </div>
}

createRoot(document.getElementById('root')!).render(<App />)
