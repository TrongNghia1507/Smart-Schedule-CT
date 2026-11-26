import { useEffect, useState, type FormEvent } from 'react'
import { anonymous, type Session } from './api'
import { ClockIcon, ErrorBox, type T } from './ui'

export function AuthPage({ onSession, t }: { onSession: (session: Session) => void; t: T }) {
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
        register ? { ...data, consent: values.has('consent') } : data))
    } catch (failure) {
      setError(failure)
    } finally {
      setBusy(false)
    }
  }

  return <main className="auth-layout">
    <aside className="auth-hero">
      <ClockIcon />
      <h1>{t('Lập lịch tuần', 'Plan your week')}</h1>
      <p>{t('Sắp xếp việc cố định và hạn chót trong cùng một lịch tuần.',
        'Bring fixed commitments and deadlines together in one weekly calendar.')}</p>
      <div className="auth-calendar" aria-hidden="true">
        <div className="auth-calendar-grid"><i /><i /><i /><i /><i /><i /></div>
      </div>
    </aside>
    <section className="panel auth-form">
      <div className="tabs" aria-label={t('Tài khoản', 'Account')}>
        <button type="button" className={!register ? 'selected' : ''} aria-pressed={!register} disabled={busy}
          onClick={() => { setRegister(false); setError(null) }}>{t('Đăng nhập', 'Sign in')}</button>
        <button type="button" className={register ? 'selected' : ''} aria-pressed={register} disabled={busy}
          onClick={() => { setRegister(true); setError(null) }}>{t('Đăng ký', 'Register')}</button>
      </div>
      <h2>{register ? t('Tạo tài khoản', 'Create an account') : t('Đăng nhập', 'Sign in')}</h2>
      <form key={String(register)} className="form-stack" onSubmit={submit}>
        {register && <label>{t('Họ và tên', 'Full name')}<input name="full_name" required minLength={2} maxLength={100} autoComplete="name" /></label>}
        <label>{t('Tên đăng nhập', 'Username')}<input name="username" required maxLength={30} autoComplete="username" /></label>
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
    </section>
  </main>
}
