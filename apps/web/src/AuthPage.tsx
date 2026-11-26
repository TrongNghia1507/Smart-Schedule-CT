import { useEffect, useState, type FormEvent } from 'react'
import { anonymous, type Session } from './api'
import { ErrorBox, Icon, type T } from './ui'

export function AuthPage({ admin, onSession, t }: { admin: boolean; onSession: (session: Session) => void; t: T }) {
  const [register, setRegister] = useState(false)
  const [groups, setGroups] = useState<string[]>([])
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (register) anonymous.get<string[]>('/auth/groups').then(setGroups).catch(setError)
  }, [register])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    const data = Object.fromEntries(values)
    setBusy(true)
    setError(null)
    try {
      onSession(await anonymous.send<Session>(register ? '/auth/register' : '/auth/login',
        register ? { ...data, consent: values.has('consent') } : { ...data, role: admin ? 'admin' : 'user' }))
    } catch (failure) {
      setError(failure)
    } finally {
      setBusy(false)
    }
  }

  return <main className="auth-layout">
    <aside className="auth-hero">
      <span className="auth-symbol"><Icon name="calendar" /></span>
      <h1>{t('Lập lịch cho cả tuần', 'Plan your whole week')}</h1>
      <p>{t('Sắp xếp việc cố định và hạn chót trong cùng một lịch tuần.',
        'Bring fixed commitments and deadlines together in one weekly calendar.')}</p>
      <div className="auth-calendar" aria-hidden="true">
        <div className="auth-calendar-days">
          {t('T2,T3,T4,T5,T6,T7,CN', 'Mon,Tue,Wed,Thu,Fri,Sat,Sun').split(',').map(day => <span key={day}>{day}</span>)}
        </div>
        <div className="auth-calendar-grid">
          <i><b>08:00</b>{t('Lên lớp', 'Class')}</i>
          <i><b>10:30</b>{t('Dự án', 'Project')}</i>
          <i><b>09:00</b>{t('Ôn bài', 'Review')}</i>
          <i><b>16:00</b>{t('Tập luyện', 'Workout')}</i>
          <i><b>11:00</b>{t('Đọc sách', 'Reading')}</i>
        </div>
      </div>
    </aside>
    <section className="panel auth-form">
      <nav className="tabs role-tabs" aria-label={t('Đăng nhập với tư cách', 'Sign in as')}>
        <a className="button" href={'/app/' + location.search} aria-current={admin ? undefined : 'page'}>
          {t('Người dùng', 'User')}
        </a>
        <a className="button" href={'/app/admin' + location.search} aria-current={admin ? 'page' : undefined}>
          {t('Quản trị viên', 'Administrator')}
        </a>
      </nav>
      <h2>{admin ? t('Đăng nhập quản trị', 'Administrator sign-in') :
        register ? t('Tạo tài khoản', 'Create an account') : t('Đăng nhập', 'Sign in')}</h2>
      <form key={String(register)} className="form-stack" onSubmit={submit}>
        {register && <label>{t('Họ và tên', 'Full name')}<input name="full_name" required minLength={2} maxLength={100} autoComplete="name" /></label>}
        <label>{t('Tên đăng nhập', 'Username')}<input name="username" required maxLength={30} autoComplete="username"
          defaultValue={admin ? 'admin' : undefined} readOnly={admin} /></label>
        {register && <>
          <label>{t('Email (không bắt buộc)', 'Email (optional)')}<input name="email" type="email" maxLength={254} autoComplete="email" /></label>
          <label>{t('Nhóm người dùng', 'User group')}<select name="user_group" defaultValue="" required>
            <option value="" disabled>{t('Chọn nhóm', 'Select a group')}</option>
            {groups.map((group, index) => <option key={group} value={group}>{t(group,
              ['University student', 'School student', 'Office worker', 'Lecturer / researcher', 'Freelancer', 'Other'][index] ?? group)}</option>)}
          </select></label>
        </>}
        <label>{t('Mật khẩu', 'Password')}<input name="password" type="password" required
          maxLength={256} minLength={register ? 6 : undefined} autoComplete={register ? 'new-password' : 'current-password'} /></label>
        {register && <>
          <label>{t('Nhập lại mật khẩu', 'Confirm password')}<input name="confirm" type="password" minLength={6}
            maxLength={256} required autoComplete="new-password" /></label>
          <label className="check"><input type="checkbox" name="consent" required />{t(
            'Tôi đồng ý lưu đánh giá và chỉ số lịch để cải thiện thuật toán.',
            'I agree to store feedback and schedule metrics to improve the algorithm.')}</label>
        </>}
        <ErrorBox error={error} t={t} />
        <button className="primary" disabled={busy || (register && !groups.length)}>
          {busy ? t('Đang xử lý…', 'Working…') : register ? t('Tạo tài khoản', 'Create account') : t('Đăng nhập', 'Sign in')}
        </button>
      </form>
      {!admin && <div className="auth-switch">
        <span>{register ? t('Đã có tài khoản?', 'Already have an account?') : t('Chưa có tài khoản?', 'New here?')}</span>
        <button type="button" className="quiet" disabled={busy}
          onClick={() => { setRegister(value => !value); setError(null) }}>
          {register ? t('Quay lại đăng nhập', 'Back to sign in') : t('Đăng ký', 'Register')}
        </button>
      </div>}
    </section>
  </main>
}
