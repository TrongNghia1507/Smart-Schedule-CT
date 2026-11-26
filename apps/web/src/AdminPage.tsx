import { useEffect, useState, type FormEvent } from 'react'
import { API, type Client, type Lang } from './api'
import { ErrorBox, type T } from './ui'

type UserRow = { id: number; username: string; full_name: string; user_group: string | null; email: string | null
  created_at: string; last_login_at: string | null; login_count: number; ratings: number }
type RatingRow = { id: number; username: string; user_group: string | null; week_start: string; updated_at: string
  overall: number; nps: number | null; adoption: string; problems: string[]; comment_good: string; comment_improve: string }
type Criterion = { key: string; title: string; short: string; n: number; satisfaction: number | null; importance: number | null
  std: number; low_share: number | null; priority_gap: number | null }
type Overview = {
  kpi: Record<string, number | null>; users: UserRow[]; ratings: RatingRow[]
  criteria: Criterion[]; tradeoffs: { key: string; a: string; b: string; n: number; toward_a: number; balanced: number; toward_b: number }[]
  problems: Record<string, number>; adoption: Record<string, number>; overall_distribution: Record<string, number>
  metric_means: Record<string, number | null>; finalized: { at: string }[]; logins: { at: string }[]
}
type Tab = 'overview' | 'ratings' | 'users' | 'settings'
const scoreValues = [1, 2, 3, 4, 5]
const percent = (score?: number | null) => score == null ? '—' : `${Math.round(100 * score)}%`

function Bars({ values, label, empty }: { values: Record<string, number>; label: string; empty: string }) {
  const maximum = Math.max(1, ...Object.values(values))
  return <section className="panel" aria-label={label}><h2>{label}</h2>
    {!Object.keys(values).length ? <p className="empty">{empty}</p> :
      <div className="bar-list">{Object.entries(values).map(([key, value]) => <div key={key}>
        <span>{key}</span><div className="bar-line"><progress value={value} max={maximum} aria-label={key} /><strong>{value}</strong></div>
      </div>)}</div>}
  </section>
}

function OverviewPanels({ data, t }: { data: Overview; t: T }) {
  const metrics: [string, unknown][] = [
    [t('Người dùng', 'Users'), data.kpi.users_total], [t('Hoạt động 7 ngày', 'Active in 7 days'), data.kpi.users_active_7d],
    [t('Đăng nhập 30 ngày', 'Sign-ins in 30 days'), data.kpi.logins_30d], [t('Lịch đã chốt', 'Finalized schedules'), data.kpi.finalized_total],
    [t('Đánh giá', 'Ratings'), data.kpi.ratings_total], [t('Hài lòng chung', 'Overall satisfaction'), data.kpi.overall_mean],
    [t('Tỷ lệ phản hồi', 'Response rate'), percent(data.kpi.response_rate)], ['NPS', data.kpi.nps],
    [t('Người dùng mới 7 ngày', 'New users in 7 days'), data.kpi.users_new_7d],
    [t('Lịch chốt đã xếp đủ', 'Complete finalized schedules'), data.kpi.finalized_complete],
    [t('Lịch chốt có xử lý xung đột', 'Finalized with conflict options'), data.kpi.finalized_with_conflict],
    [t('Tỷ lệ chấp nhận lịch', 'Schedule acceptance'), percent(data.kpi.accept_rate)],
    [t('Việc xếp đủ', 'Task coverage'), percent(data.metric_means.coverage_task_ratio)],
    [t('Đạt ưu tiên', 'Priority coverage'), percent(data.metric_means.priority_weighted_ratio)],
    [t('Phiên trung bình (phút)', 'Average session (minutes)'), data.metric_means.avg_chunk_min],
    [t('Ngày nặng nhất (phút)', 'Busiest day (minutes)'), data.metric_means.max_day_minutes],
    [t('Mức lấp đầy giờ rảnh', 'Free time utilization'), percent(data.metric_means.utilization_ratio)],
  ]
  const empty = t('Chưa có dữ liệu.', 'No data yet.')
  const lastDays = Array.from({ length: 14 }, (_, index) => {
    const day = new Date(Date.now() - (13 - index) * 86400000)
    return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh', dateStyle: 'short' }).format(day)
  })
  const byDay = (rows: { at: string }[]) => {
    const date = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh', dateStyle: 'short' })
    const totals: Record<string, number> = Object.fromEntries(lastDays.map(day => [day, 0]))
    for (const row of rows) {
      const key = date.format(new Date(row.at))
      if (key in totals) totals[key]++
    }
    return Object.fromEntries(Object.entries(totals).map(([key, count]) => [key.slice(5), count]))
  }
  return <>
    <div className="metric-grid">{metrics.map(([label, value]) => <div key={label}>
      <strong>{value == null ? '—' : String(value)}</strong><span>{label}</span>
    </div>)}</div>
    <section className="panel">
      <h2>{t('Hài lòng theo tiêu chí', 'Satisfaction by criterion')}</h2>
      <div className="table-wrap"><table><thead><tr>{[
        t('Tiêu chí', 'Criterion'), t('Số đánh giá', 'Count'), t('Hài lòng', 'Satisfaction'), t('Quan trọng', 'Importance'),
        t('Tỷ lệ điểm thấp', 'Low score share'), t('Khoảng cách ưu tiên', 'Priority gap'),
      ].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>
        {data.criteria.map((item, index) => <tr key={item.key}>
          <th scope="row">{t(item.short, ['Coverage', 'Priority', 'Timeliness', 'Continuity', 'Balance', 'Constraints', 'Feasibility'][index])}</th>
          <td>{item.n}</td><td>{item.satisfaction ?? '—'}</td><td>{item.importance ?? '—'}</td>
          <td>{percent(item.low_share)}</td><td>{item.priority_gap ?? '—'}</td>
        </tr>)}
      </tbody></table></div>
    </section>
    <div className="multi-panel">
      <Bars values={data.overall_distribution} label={t('Phân bố điểm hài lòng', 'Satisfaction distribution')} empty={empty} />
      <Bars values={data.adoption} label={t('Cách sử dụng lịch', 'Schedule adoption')} empty={empty} />
      <Bars values={data.problems} label={t('Vấn đề được ghi nhận', 'Reported issues')} empty={empty} />
    </div>
    <section className="panel">
      <h2>{t('Phân bố lựa chọn đánh đổi', 'Trade-off preferences')}</h2>
      <div className="table-wrap"><table><thead><tr><th>A</th><th>B</th><th>{t('Nghiêng A', 'Prefer A')}</th>
        <th>{t('Cân bằng', 'Balanced')}</th><th>{t('Nghiêng B', 'Prefer B')}</th></tr></thead><tbody>
        {data.tradeoffs.map(row => <tr key={row.key}><td>{row.a}</td><td>{row.b}</td>
          <td>{row.toward_a}</td><td>{row.balanced}</td><td>{row.toward_b}</td></tr>)}
      </tbody></table></div>
    </section>
    <div className="multi-panel">
      <Bars values={byDay(data.logins)} label={t('Đăng nhập 14 ngày qua', 'Sign-ins in the last 14 days')} empty={empty} />
      <Bars values={byDay(data.finalized)} label={t('Lịch chốt 14 ngày qua', 'Finalized in the last 14 days')} empty={empty} />
      <Bars values={byDay(data.ratings.map(row => ({ at: row.updated_at })))} label={t('Đánh giá 14 ngày qua', 'Ratings in the last 14 days')} empty={empty} />
    </div>
  </>
}

function PasswordForm({ client, t, onChanged }: { client: Client; t: T; onChanged: () => void }) {
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const values = Object.fromEntries(new FormData(event.currentTarget))
    setBusy(true); setError(null)
    try { await client.send('/admin/password', values); onChanged() }
    catch (error) { setError(error) }
    finally { setBusy(false) }
  }
  return <section className="panel narrow"><h2>{t('Đổi mật khẩu quản trị', 'Change admin password')}</h2>
    <form onSubmit={submit} className="form-stack">
      <label>{t('Mật khẩu hiện tại', 'Current password')}<input name="current" type="password" autoComplete="current-password" required /></label>
      <label>{t('Mật khẩu mới', 'New password')}<input name="new" type="password" autoComplete="new-password" required minLength={6} /></label>
      <label>{t('Nhập lại mật khẩu mới', 'Confirm new password')}<input name="confirm" type="password" autoComplete="new-password" required minLength={6} /></label>
      <ErrorBox error={error} t={t} /><button className="primary" disabled={busy}>{t('Đổi mật khẩu', 'Change password')}</button>
    </form>
  </section>
}

export function AdminPage({ client, onChanged, lang, t }: { client: Client; onChanged: () => void; lang: Lang; t: T }) {
  const [tab, setTab] = useState<Tab>('overview')
  const [score, setScore] = useState('')
  const [group, setGroup] = useState('')
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    let active = true
    client.get<Overview>('/admin/overview').then(result => { if (active) setData(result) })
      .catch(error => { if (active) setError(error) })
    return () => { active = false }
  }, [client])

  const tabs: [Tab, string][] = [['overview', t('Tổng quan', 'Overview')], ['ratings', t('Đánh giá', 'Ratings')],
    ['users', t('Người dùng', 'Users')], ['settings', t('Cài đặt', 'Settings')]]
  const format = (value: string | null) => value ? new Date(value).toLocaleString(lang === 'vi' ? 'vi-VN' : 'en-GB',
    { timeZone: 'Asia/Ho_Chi_Minh', dateStyle: 'short', timeStyle: 'short' }) : '—'
  const filtered = data?.ratings.filter(row => (!score || row.overall === +score) && (!group || (row.user_group ?? '—') === group)) ?? []
  const groups = [...new Set(data?.ratings.map(row => row.user_group ?? '—'))].sort()
  const query = new URLSearchParams()
  if (score) query.set('score', score)
  if (group) query.set('group', group)

  return <>
    <div className="page-heading"><div><h1>{t('Quản trị', 'Administration')}</h1>
      <p>{t('Theo dõi người dùng, lịch đã chốt và đánh giá.', 'Track users, finalized schedules, and feedback.')}</p></div></div>
    <div className="tabs">{tabs.map(([id, label]) => <button key={id} className={tab === id ? 'selected' : ''}
      aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}</div>
    <ErrorBox error={error} t={t} />
    {tab === 'settings' ? <PasswordForm client={client} t={t} onChanged={onChanged} /> :
      !data && !error ? <p role="status">{t('Đang tải báo cáo…', 'Loading report…')}</p> : null}
    {data && tab === 'overview' && <OverviewPanels data={data} t={t} />}
    {data && tab === 'ratings' && <section className="panel">
      <div className="section-head"><h2>{t('Đánh giá chi tiết', 'Rating details')}</h2>
        <a className="button" href={`${API}/admin/ratings.csv?${query}`}>{t('Tải CSV', 'Download CSV')}</a></div>
      <div className="form-grid">
        <label>{t('Hài lòng chung', 'Overall satisfaction')}<select value={score} onChange={event => setScore(event.target.value)}>
          <option value="">{t('Tất cả điểm', 'All scores')}</option>{scoreValues.map(value => <option key={value}>{value}</option>)}
        </select></label>
        <label>{t('Nhóm người dùng', 'User group')}<select value={group} onChange={event => setGroup(event.target.value)}>
          <option value="">{t('Tất cả nhóm', 'All groups')}</option>{groups.map(value => <option key={value}>{value}</option>)}
        </select></label>
      </div>
      <p className="muted">{filtered.length}/{data.ratings.length} {t('đánh giá', 'ratings')}</p>
      <div className="table-wrap"><table><thead><tr>{[t('Người dùng', 'User'), t('Nhóm', 'Group'), t('Tuần', 'Week'),
        t('Cập nhật', 'Updated'), t('Hài lòng', 'Satisfaction'), 'NPS', t('Cách dùng', 'Adoption'), t('Góp ý', 'Comments')].map(label =>
        <th key={label}>{label}</th>)}</tr></thead><tbody>{filtered.map(row => <tr key={row.id}>
          <th scope="row">{row.username}</th><td>{row.user_group ?? '—'}</td><td>{row.week_start}</td><td>{format(row.updated_at)}</td>
          <td>{row.overall}</td><td>{row.nps ?? '—'}</td><td>{row.adoption}</td>
          <td>{[...row.problems, row.comment_good, row.comment_improve].filter(Boolean).join(' · ') || '—'}</td>
        </tr>)}</tbody></table></div>
    </section>}
    {data && tab === 'users' && <section className="panel">
      <div className="section-head"><h2>{t('Danh sách người dùng', 'User list')}</h2>
        <a className="button" href={API + '/admin/users.csv'}>{t('Tải CSV', 'Download CSV')}</a></div>
      <div className="table-wrap"><table><thead><tr>{[
        t('Tên đăng nhập', 'Username'), t('Họ tên', 'Name'), t('Nhóm', 'Group'), 'Email', t('Đăng ký', 'Registered'),
        t('Lần đăng nhập gần nhất', 'Last sign-in'), t('Số lượt đăng nhập', 'Sign-ins'), t('Đánh giá', 'Ratings'),
      ].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{data.users.map(user => <tr key={user.id}>
        <th scope="row">{user.username}</th><td>{user.full_name}</td><td>{user.user_group ?? '—'}</td><td>{user.email ?? '—'}</td>
        <td>{format(user.created_at)}</td><td>{format(user.last_login_at)}</td><td>{user.login_count}</td><td>{user.ratings}</td>
      </tr>)}</tbody></table></div>
    </section>}
  </>
}
