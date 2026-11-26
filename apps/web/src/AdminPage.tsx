import { useEffect, useState, type FormEvent } from 'react'
import { API, type Client, type Lang } from './api'
import { dateInWeek, vietnamDay } from './dates'
import { ErrorBox, type T } from './ui'

type UserRow = { id: number; username: string; full_name: string; user_group: string | null; email: string | null
  created_at: string; last_login_at: string | null; login_count: number; ratings: number }
type RatingRow = { id: number; username: string; user_group: string | null; week_start: string; created_at: string; updated_at: string
  overall: number; nps: number | null; adoption: string; problems: string[]; comment_good: string; comment_improve: string }
type Criterion = { key: string; title: string; short: string; n: number; satisfaction: number | null; importance: number | null
  std: number; low_share: number | null; priority_gap: number | null }
type Overview = {
  kpi: Record<string, number | null>; users: UserRow[]; ratings: RatingRow[]
  criteria: Criterion[]; tradeoffs: { key: string; a: string; b: string; mean: number | null; toward_a: number; balanced: number; toward_b: number }[]
  problems: Record<string, number>; adoption: Record<string, number>; overall_distribution: Record<string, number>
  metric_means: Record<string, number | null>; finalized: { at: string }[]
}
type Tab = 'overview' | 'ratings' | 'users' | 'settings'
const scoreValues = [1, 2, 3, 4, 5]
const percent = (score?: number | null) => score == null ? '—' : `${Math.round(100 * score)}%`
const criterionNames = ['Coverage', 'Priority', 'Timeliness', 'Continuity', 'Balance', 'Constraints', 'Feasibility']

function Bars({ values, label, empty }: { values: Record<string, number>; label: string; empty: string }) {
  const maximum = Math.max(1, ...Object.values(values))
  return <section className="panel" aria-label={label}><h2>{label}</h2>
    {!Object.keys(values).length ? <p className="empty">{empty}</p> :
      <div className="bar-list">{Object.entries(values).map(([key, value]) => <div key={key}>
        <span>{key}</span><div className="bar-line"><progress value={value} max={maximum} aria-label={key} /><strong>{value}</strong></div>
      </div>)}</div>}
  </section>
}

function CriterionMatrix({ criteria, t }: { criteria: Criterion[]; t: T }) {
  const points = new Map<string, { left: number; top: number; names: string[]; values: string }>()
  for (const [index, item] of criteria.entries()) {
    if (item.importance == null || item.satisfaction == null) continue
    const values = `${item.importance} / ${item.satisfaction}`
    const point = points.get(values) ?? {
      left: (item.importance - 0.5) * 20, top: (5.5 - item.satisfaction) * 20, names: [], values,
    }
    point.names.push(t(item.short, criterionNames[index]))
    points.set(values, point)
  }
  return <section className="panel"><h2>{t('Ma trận mức quan trọng – mức hài lòng', 'Importance–satisfaction matrix')}</h2>
    {!points.size ? <p className="empty">{t('Chưa có dữ liệu.', 'No data yet.')}</p> : <>
      <div className="matrix">
        <span>{t('Hài lòng', 'Satisfaction')}</span>
        <div className="matrix-y" aria-hidden="true">{[...scoreValues].reverse().map(value => <span key={value}>{value}</span>)}</div>
        <div className="matrix-plot">
          {[...points.values()].map(point => <span key={point.values} className="matrix-point" tabIndex={0}
            style={{ left: `${point.left}%`, top: `${point.top}%` }}
            aria-label={`${point.names.join(', ')} · ${t('Quan trọng / Hài lòng', 'Importance / Satisfaction')} ${point.values}`}>
            <span aria-hidden="true">{point.names.join(', ')} · {point.values}</span>
          </span>)}
        </div>
        <div className="matrix-x" aria-hidden="true">{scoreValues.map(value => <span key={value}>{value}</span>)}</div>
        <span className="matrix-x-label">{t('Mức quan trọng', 'Importance')}</span>
      </div>
      <p className="muted">{t('Ưu tiên các tiêu chí ở góc dưới bên phải, nơi tầm quan trọng cao và mức hài lòng thấp.',
        'Prioritize criteria in the lower-right quadrant, where importance is high and satisfaction is low.')}</p>
    </>}
  </section>
}

function ActivityTrend({ data, t }: { data: Overview; t: T }) {
  const today = vietnamDay(new Date())
  const days = Array.from({ length: 30 }, (_, index) => dateInWeek(today, index - 29))
  const count = (timestamps: string[]) => {
    const totals = new Map(days.map(day => [day, 0]))
    for (const timestamp of timestamps) {
      const day = vietnamDay(new Date(timestamp))
      const total = totals.get(day)
      if (total !== undefined) totals.set(day, total + 1)
    }
    return [...totals.values()]
  }
  const series = [
    { label: t('Đăng ký mới', 'New registrations'), values: count(data.users.map(user => user.created_at)), color: 'var(--accent)' },
    { label: t('Lịch đã chốt', 'Finalized schedules'), values: count(data.finalized.map(row => row.at)), color: 'var(--mint-ink)' },
    { label: t('Đánh giá', 'Ratings'), values: count(data.ratings.map(row => row.created_at)), color: 'var(--amber-ink)' },
  ]
  const step = Math.max(1, Math.ceil(Math.max(...series.flatMap(item => item.values)) / 4))
  const x = (index: number) => 35 + index * 25
  const y = (value: number) => 145 - value / step * 32
  const labelDay = (day: string) => `${day.slice(8)}/${day.slice(5, 7)}`
  return <section className="panel"><h2>{t('Xu hướng 30 ngày gần nhất', 'Last 30 days')}</h2>
    <div className="inline chart-legend">{series.map(item => <span key={item.label}>
      <i className="swatch" style={{ background: item.color }} />{item.label}
    </span>)}</div>
    <div className="table-wrap"><svg className="trend-chart" viewBox="0 0 788 176" aria-hidden="true">
      {[0, 1, 2, 3, 4].map(tick => <g key={tick} className="chart-tick">
        <text x="27" y={y(step * tick) + 4} textAnchor="end">{step * tick}</text>
        <line x1={x(0)} x2={x(29)} y1={y(step * tick)} y2={y(step * tick)} />
      </g>)}
      {series.map((item, index) => <polyline key={item.label} points={item.values.map((value, day) => `${x(day)},${y(value)}`).join(' ')}
        fill="none" stroke={item.color} strokeWidth="2" strokeDasharray={['', '7 4', '2 3'][index]} />)}
      {[0, 7, 14, 21, 29].map(day => <text className="chart-tick" key={day} x={x(day)} y="166" textAnchor="middle">{labelDay(days[day])}</text>)}
    </svg></div>
    <details><summary>{t('Số liệu theo ngày', 'Daily counts')}</summary>
      <div className="table-wrap"><table><thead><tr><th>{t('Ngày', 'Date')}</th>
        {series.map(item => <th key={item.label}>{item.label}</th>)}</tr></thead>
        <tbody>{days.map((day, index) => <tr key={day}><th scope="row">{labelDay(day)}</th>
          {series.map(item => <td key={item.label}>{item.values[index]}</td>)}</tr>)}</tbody>
      </table></div>
    </details>
  </section>
}

function OverviewPanels({ data, t }: { data: Overview; t: T }) {
  const metrics: [string, unknown][] = [
    [t('Người dùng', 'Users'), data.kpi.users_total], [t('Hoạt động 7 ngày', 'Active in 7 days'), data.kpi.users_active_7d],
    [t('Đăng nhập 30 ngày', 'Sign-ins in 30 days'), data.kpi.logins_30d], [t('Lịch đã chốt', 'Finalized schedules'), data.kpi.finalized_total],
    [t('Đánh giá', 'Ratings'), data.kpi.ratings_total], [t('Hài lòng chung', 'Overall satisfaction'), data.kpi.overall_mean],
    [t('Người đã đánh giá', 'People who rated'), data.kpi.raters],
    [t('Độ lệch chuẩn hài lòng chung', 'Overall satisfaction standard deviation'), data.kpi.overall_std],
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
  const priorities = data.criteria.map((item, index) => ({ ...item, label: t(item.short, criterionNames[index]) }))
    .filter(item => item.priority_gap != null).sort((a, b) => b.priority_gap! - a.priority_gap!).slice(0, 2)
  return <>
    <div className="metric-grid">{metrics.map(([label, value]) => <div key={label}>
      <strong>{value == null ? '—' : String(value)}</strong><span>{label}</span>
    </div>)}</div>
    <div className="admin-criteria"><section className="panel">
      <h2>{t('Hài lòng theo tiêu chí', 'Satisfaction by criterion')}</h2>
      <div className="table-wrap"><table><thead><tr>{[
        t('Tiêu chí', 'Criterion'), t('Số đánh giá', 'Count'), t('Hài lòng', 'Satisfaction'), t('Quan trọng', 'Importance'),
        t('Độ lệch chuẩn', 'Standard deviation'), t('Tỷ lệ điểm thấp (≤2)', 'Low score share (≤2)'), t('Khoảng cách ưu tiên', 'Priority gap'),
      ].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>
        {data.criteria.map((item, index) => <tr key={item.key}>
          <th scope="row">{t(item.short, criterionNames[index])}</th>
          <td>{item.n}</td><td>{item.satisfaction ?? '—'}</td><td>{item.importance ?? '—'}</td>
          <td>{item.std}</td><td>{percent(item.low_share)}</td><td>{item.priority_gap ?? '—'}</td>
        </tr>)}
      </tbody></table></div>
      <p className="muted">{t('Khoảng cách ưu tiên là trung bình của mức quan trọng × (5 − mức hài lòng).',
        'The priority gap is the mean of importance × (5 − satisfaction).')}</p>
      {priorities.length > 0 && <div className="notice"><strong>{t('Tiêu chí cần ưu tiên cải thiện', 'Improvement priorities')}</strong>
        <ol className="simple-list">{priorities.map(item => <li key={item.key}>{item.label} · {item.priority_gap}</li>)}</ol>
      </div>}
    </section><CriterionMatrix criteria={data.criteria} t={t} /></div>
    <div className="multi-panel">
      <Bars values={data.overall_distribution} label={t('Phân bố điểm hài lòng', 'Satisfaction distribution')} empty={empty} />
      <Bars values={data.adoption} label={t('Cách sử dụng lịch', 'Schedule adoption')} empty={empty} />
      <Bars values={data.problems} label={t('Vấn đề được ghi nhận', 'Reported issues')} empty={empty} />
    </div>
    <section className="panel">
      <h2>{t('Phân bố lựa chọn đánh đổi', 'Trade-off preferences')}</h2>
      <div className="table-wrap"><table><thead><tr><th>A</th><th>B</th><th>{t('Nghiêng A', 'Prefer A')}</th>
        <th>{t('Cân bằng', 'Balanced')}</th><th>{t('Nghiêng B', 'Prefer B')}</th>
        <th>{t('Xu hướng (−2 = A, +2 = B)', 'Mean (−2 = A, +2 = B)')}</th></tr></thead><tbody>
        {data.tradeoffs.map(row => <tr key={row.key}><td>{row.a}</td><td>{row.b}</td>
          <td>{row.toward_a}</td><td>{row.balanced}</td><td>{row.toward_b}</td><td>{row.mean ?? '—'}</td></tr>)}
      </tbody></table></div>
    </section>
    <ActivityTrend data={data} t={t} />
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

function FilterChoices({ label, options, selected, change, t }: {
  label: string; options: string[]; selected: string[]; change: (values: string[] | null) => void; t: T
}) {
  return <fieldset className="compact">
    <legend>{label}</legend>
    <div className="inline filter-choices">{options.map(value => <label className="check" key={value}>
      <input type="checkbox" checked={selected.includes(value)} onChange={event => {
        change(event.target.checked ? [...selected, value] : selected.filter(item => item !== value))
      }} />{value}
    </label>)}</div>
    <button className="quiet" disabled={selected.length === options.length} onClick={() => change(null)}>{t('Chọn tất cả', 'Select all')}</button>
    <button className="quiet" disabled={!selected.length} onClick={() => change([])}>{t('Bỏ chọn tất cả', 'Clear selection')}</button>
  </fieldset>
}

export function AdminPage({ client, onChanged, lang, t }: { client: Client; onChanged: () => void; lang: Lang; t: T }) {
  const [tab, setTab] = useState<Tab>('overview')
  const [scoreFilter, setScoreFilter] = useState<string[] | null>(null)
  const [groupFilter, setGroupFilter] = useState<string[] | null>(null)
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
  const scores = scoreValues.map(String)
  const groups = [...new Set(data?.ratings.map(row => row.user_group || '—'))].sort()
  const selectedScores = scoreFilter ?? scores
  const selectedGroups = groupFilter ?? groups
  const filtered = data?.ratings.filter(row => selectedScores.includes(String(row.overall)) && selectedGroups.includes(row.user_group || '—')) ?? []
  const groupCounts = new Map<string, number>()
  for (const row of data?.users ?? []) {
    const group = row.user_group || '—'
    groupCounts.set(group, (groupCounts.get(group) ?? 0) + 1)
  }
  const query = new URLSearchParams()
  if (!selectedScores.length || !selectedGroups.length) query.set('empty', 'true')
  else {
    scoreFilter?.forEach(score => query.append('score', score))
    groupFilter?.forEach(group => query.append('group', group))
  }

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
        <FilterChoices label={t('Hài lòng chung', 'Overall satisfaction')} options={scores} selected={selectedScores} change={setScoreFilter} t={t} />
        <FilterChoices label={t('Nhóm người dùng', 'User group')} options={groups} selected={selectedGroups} change={setGroupFilter} t={t} />
      </div>
      <p className="muted" role="status">{filtered.length}/{data.ratings.length} {t('đánh giá', 'ratings')}</p>
      <div className="table-wrap"><table><thead><tr>{[t('Người dùng', 'User'), t('Nhóm', 'Group'), t('Tuần', 'Week'),
        t('Cập nhật', 'Updated'), t('Hài lòng', 'Satisfaction'), 'NPS', t('Cách dùng', 'Adoption'),
        t('Vấn đề', 'Issues'), t('Điều tốt', 'What worked'), t('Cần cải thiện', 'What to improve')].map(label =>
        <th key={label}>{label}</th>)}</tr></thead><tbody>{filtered.map(row => <tr key={row.id}>
          <th scope="row">{row.username}</th><td>{row.user_group ?? '—'}</td><td>{row.week_start}</td><td>{format(row.updated_at)}</td>
          <td>{row.overall}</td><td>{row.nps ?? '—'}</td><td>{row.adoption}</td>
          <td>{row.problems.join(' · ') || '—'}</td><td>{row.comment_good || '—'}</td><td>{row.comment_improve || '—'}</td>
        </tr>)}</tbody></table></div>
    </section>}
    {data && tab === 'users' && <><Bars values={Object.fromEntries(groupCounts)} label={t('Cơ cấu nhóm người dùng', 'User group distribution')}
      empty={t('Chưa có người dùng nào đăng ký.', 'No users have registered.')} /><section className="panel">
      <div className="section-head"><h2>{t('Danh sách người dùng', 'User list')}</h2>
        <a className="button" href={API + '/admin/users.csv'}>{t('Tải CSV', 'Download CSV')}</a></div>
      <div className="table-wrap"><table><thead><tr>{[
        t('Tên đăng nhập', 'Username'), t('Họ tên', 'Name'), t('Nhóm', 'Group'), 'Email', t('Đăng ký', 'Registered'),
        t('Lần đăng nhập gần nhất', 'Last sign-in'), t('Số lượt đăng nhập', 'Sign-ins'), t('Đánh giá', 'Ratings'),
      ].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{data.users.map(user => <tr key={user.id}>
        <th scope="row">{user.username}</th><td>{user.full_name}</td><td>{user.user_group ?? '—'}</td><td>{user.email ?? '—'}</td>
        <td>{format(user.created_at)}</td><td>{format(user.last_login_at)}</td><td>{user.login_count}</td><td>{user.ratings}</td>
      </tr>)}</tbody></table></div>
    </section></>}
  </>
}
