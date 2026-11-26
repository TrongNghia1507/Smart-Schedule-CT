import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Icon, confirmDiscard, ErrorBox, translate } from './components/ui'
import { anonymous, ApiError, createClient, type Draft, type Lang, type Session } from './lib/api'
import { currentMonday, weekLabel } from './lib/dates'
import { AuthPage } from './pages/AuthPage'
import { DraftPage, type ChangeDraft } from './pages/DraftPage'
import './styles.css'

type Theme = 'light' | 'dark'
type Page = 'input' | 'calendar' | 'history' | 'admin'
const base = '/app/'
const PlannerPage = lazy(() => import('./pages/PlannerPage').then(module => ({ default: module.PlannerPage })))
const HistoryPage = lazy(() => import('./pages/HistoryPage').then(module => ({ default: module.HistoryPage })))
const AdminPage = lazy(() => import('./pages/AdminPage').then(module => ({ default: module.AdminPage })))

function initialPreference<T extends string>(key: string, values: T[], fallback: T): T {
  const query = new URLSearchParams(location.search).get(key)
  const saved = localStorage.getItem(key)
  return values.find(value => value === query) ?? values.find(value => value === saved) ?? fallback
}

function initialPage(): Page {
  const section = location.pathname.slice(base.length).split('/')[0]
  return section === 'calendar' || section === 'history' || section === 'admin' ? section : 'input'
}

function App() {
  const [lang, setLang] = useState(() => initialPreference<Lang>('lang', ['vi', 'en'], 'vi'))
  const [theme, setTheme] = useState(() => initialPreference<Theme>('theme', ['light', 'dark'], 'light'))
  const [session, setSession] = useState<Session | null | undefined>(undefined)
  const [error, setError] = useState<unknown>(null)
  const [authNotice, setAuthNotice] = useState(false)
  const [page, setPage] = useState(initialPage)
  const adminRoute = page === 'admin'
  const planner = session?.user.role === 'user' && !adminRoute
  const [draft, setDraft] = useState<Draft | null>(null)
  const [keptWeeks, setKeptWeeks] = useState<string[]>([])
  const [switchingWeek, setSwitchingWeek] = useState(false)
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
    if (!planner) return
    let active = true
    client.get<Draft>('/draft').then(value => { if (active) setDraft(value) })
      .catch(failure => { if (active) setError(failure) })
    return () => { active = false }
  }, [client, planner, loadVersion, lang])

  useEffect(() => {
    if (session?.user.role === 'admin' && !adminRoute) {
      history.replaceState(null, '', base + 'admin' + location.search)
      setPage('admin')
    }
  }, [session, adminRoute])

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

  const thisWeek = currentMonday()
  const weekChoice = `${session?.user.id ?? ''}:${draft?.settings.week_start ?? ''}`
  const askAboutWeek = planner && draft && draft.settings.week_start < thisWeek && !keptWeeks.includes(weekChoice)

  async function switchWeek() {
    if (!draft || !confirmDiscard(document, t)) return
    setSwitchingWeek(true)
    setError(null)
    try {
      await change({ action: 'settings', week_start: thisWeek, sleep_start: draft.settings.sleep.start, sleep_end: draft.settings.sleep.end })
    } catch (failure) {
      setError(failure)
    } finally {
      setSwitchingWeek(false)
    }
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

  const tabs = [
    { id: 'input', label: t('Nhập dữ liệu', 'Input'), icon: 'list' },
    { id: 'calendar', label: t('Lịch tuần', 'Calendar'), icon: 'calendar' },
    { id: 'history', label: t('Lịch sử', 'History'), icon: 'history' },
  ] as const
  const initials = session?.user.full_name.trim().split(/\s+/).slice(-2).map(word => [...word][0]).join('').toUpperCase()
  const brand = <a href={base} className="brand" onClick={event => {
    if (planner && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      event.preventDefault()
      navigate('input')
    }
  }}><span className="brand-mark"><Icon name="clock" /></span><span>Smart Schedule <b>CT</b></span></a>
  return <div className={planner ? 'app-shell planning-shell' : 'app-shell'} onChange={event => {
    const form = (event.target as HTMLElement).closest<HTMLFormElement>('form[data-track]')
    if (form) form.dataset.dirty = 'true'
  }}>
    {planner && <aside className="sidebar">
      {brand}
      <nav aria-label={t('Điều hướng chính', 'Main navigation')}>{tabs.map(({id, label, icon}) =>
        <a key={id} href={base + (id === 'input' ? '' : id) + location.search} aria-current={page === id ? 'page' : undefined}
          onClick={event => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
            event.preventDefault()
            navigate(id)
          }}><Icon name={icon} /><span>{label}</span></a>)}</nav>
      {draft && <div className="sidebar-week">
        <Icon name="calendar" />
        <div><span>{t('Tuần lập lịch', 'Planning week')}</span><strong>{weekLabel(draft.settings.week_start, lang)}</strong></div>
      </div>}
    </aside>}
    <div className="app-content">
    <header className="topbar">
      <div className="topbar-inner">
        {planner ? <span className="topbar-label">{t('Không gian lập lịch', 'Planning workspace')}</span> : brand}
        <div className="account">
          <label className="compact-label"><span className="sr-only">{t('Ngôn ngữ', 'Language')}</span>
            <select aria-label={t('Ngôn ngữ', 'Language')} value={lang} onChange={event => preference('lang', event.target.value)}>
              <option value="vi">VI</option><option value="en">EN</option>
            </select></label>
          <button className="icon-button" title={t('Đổi giao diện sáng / tối', 'Toggle light / dark theme')}
            aria-label={t('Đổi giao diện sáng / tối', 'Toggle light / dark theme')}
            onClick={() => preference('theme', theme === 'light' ? 'dark' : 'light')}>
            <Icon name={theme === 'light' ? 'moon' : 'sun'} />
          </button>
          {planner && <a className="button quiet" href={base + 'admin' + location.search} onClick={event => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
            event.preventDefault()
            navigate('admin')
          }}>{t('Quản trị', 'Admin')}</a>}
          {session && <><span className="account-person">
            <span className="account-avatar" aria-hidden="true">{initials}</span>
            <span className="account-name" title={session.user.full_name}>{session.user.full_name}</span></span>
            <button onClick={() => void signOut()}>{t('Đăng xuất', 'Sign out')}</button></>}
        </div>
      </div>
    </header>
    {session === null ? <>
      {authNotice && <div className="auth-message notice" role="status">{t('Đã đổi mật khẩu. Hãy đăng nhập lại.',
        'Password changed. Sign in again.')}</div>}
      <AuthPage key={String(adminRoute)} admin={adminRoute} t={t}
        onSession={value => { setAuthNotice(false); setSession(value) }} />
    </> : <main className="workspace">
      <ErrorBox error={error} t={t} reload={reload} />
      {askAboutWeek && <section className="notice" aria-label={t('Tuần của bản nháp', 'Draft week')}>
        <p>{t('Bản nháp đang dùng tuần cũ', 'Your draft is set to an earlier week')} · {weekLabel(draft.settings.week_start, lang)}</p>
        <div className="inline">
          <button disabled={switchingWeek} onClick={() => setKeptWeeks(weeks => [...weeks, weekChoice])}>{t('Giữ tuần cũ', 'Keep draft week')}</button>
          <button disabled={switchingWeek} onClick={() => void switchWeek()}>{t('Chuyển sang tuần hiện tại', 'Switch to current week')}</button>
        </div>
      </section>}
      {session === undefined && error ? <button onClick={() => location.reload()}>{t('Thử lại', 'Retry')}</button> : null}
      <Suspense fallback={<p role="status">{t('Đang tải…', 'Loading…')}</p>}>
        {adminRoute && session?.user.role === 'admin' && <AdminPage client={client} lang={lang} t={t}
          onChanged={() => { endSession(); setAuthNotice(true) }} />}
        {planner && draft && page === 'calendar' && <PlannerPage draft={draft} client={client} change={change}
          reload={reload} toInput={() => navigate('input')} lang={lang} t={t} />}
        {planner && draft && page === 'history' && <HistoryPage draft={draft} client={client}
          onRestore={value => { setDraft(value); navigate('input', false) }} reload={reload} lang={lang} t={t} />}
      </Suspense>
      {adminRoute && session?.user.role === 'user' && <section className="panel narrow">
        <h1>{t('Khu vực quản trị', 'Administrator area')}</h1>
        <p>{t('Bạn đang dùng tài khoản lập lịch. Đăng xuất để đăng nhập bằng tài khoản quản trị viên.',
          'You are signed in as a planner. Sign out to enter with an administrator account.')}</p>
        <div className="inline">
          <button onClick={() => navigate('input')}>{t('Về trang người dùng', 'Back to planner')}</button>
          <button className="primary" onClick={() => void signOut()}>{t('Đăng xuất để vào quản trị', 'Sign out for admin access')}</button>
        </div>
      </section>}
      {planner && draft && page === 'input' && <DraftPage draft={draft} client={client} change={change} adopt={setDraft}
        reload={reload} advance={() => navigate('calendar')} lang={lang} t={t} />}
      {(!session || (planner && !draft)) && (error ? session && <button onClick={reload}>{t('Thử lại', 'Retry')}</button> :
        <p role="status">{t('Đang tải…', 'Loading…')}</p>)}
    </main>}
    </div>
  </div>
}

createRoot(document.getElementById('root')!).render(<App />)
