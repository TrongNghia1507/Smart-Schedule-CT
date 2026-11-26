import { useEffect, useState, type FormEvent } from 'react'
import type { Client } from '../lib/api'
import { ErrorBox, type T } from './ui'

type Scores = { satisfaction: number | null; importance: number }
type Rating = {
  criteria: Record<string, Scores>; tradeoffs: Record<string, number>; overall: number; adoption: string
  vs_manual: number | null; nps: number; conflict_clarity: number | null; problems: string[]
  comment_good: string; comment_improve: string
}
type Schema = {
  criteria: { key: string; title: string; question: string }[]
  tradeoffs: { key: string; a: string; b: string }[]; tradeoff_labels: Record<string, string>
  adoption: string[]; vs_manual: Record<string, string>; no_baseline: string; problems: string[]
}
type Detail = { rating: Rating | null; facts: Record<string, string[]>; metrics: {
  options_applied: number; tasks_fully_placed: number; tasks_total: number; chunks_total: number
  on_time_ratio: number | null; max_day_minutes: number
} }
type Choice = [number | string, string]
const scores = [1, 2, 3, 4, 5]
const criterionNames = ['Coverage', 'Priority', 'Timeliness', 'Continuity', 'Balance', 'Constraints', 'Feasibility']

function Select({ label, name, choices, initial, t }: {
  label: string; name: string; choices: Choice[]; initial?: number | string; t: T
}) {
  return <label>{label}<select name={name} defaultValue={initial ?? ''} required>
    <option value="" disabled>{t('Chọn câu trả lời', 'Choose an answer')}</option>
    {choices.map(([key, title]) => <option key={key} value={key}>{title}</option>)}
  </select></label>
}

export function RatingForm({ client, ratingKey, t }: { client: Client; ratingKey: string; t: T }) {
  const [info, setInfo] = useState<{ schema: Schema; details: Detail } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const path = `/ratings/${ratingKey}`

  useEffect(() => {
    let active = true
    Promise.all([client.get<Schema>('/ratings/schema'), client.get<Detail>(path)])
      .then(([schema, details]) => { if (active) setInfo({ schema, details }) })
      .catch(error => { if (active) setError(error) })
    return () => { active = false }
  }, [client, path])

  if (!info) return error ? <ErrorBox error={error} t={t} /> : <p role="status">{t('Đang tải đánh giá…', 'Loading rating…')}</p>
  const { schema, details: { rating, metrics, facts } } = info
  if (saved && rating) {
    const rows = schema.criteria.map((item, index) => ({
      key: item.key, label: t(item.title, criterionNames[index]), ...rating.criteria[item.key],
    }))
    const weighted = rows.reduce((total, { satisfaction, importance }) => satisfaction == null ? total :
      { score: total.score + satisfaction * importance, weight: total.weight + importance }, { score: 0, weight: 0 })
    return <section className="form-stack rating-summary">
      <p className="notice" role="status">{t('Đã lưu đánh giá.', 'Rating saved.')}</p>
      {weighted.weight > 0 && <div className="metric-grid rating-metrics"><div>
        <strong>{(weighted.score / weighted.weight).toFixed(1)} / 5</strong>
        <span>{t('Điểm hài lòng có trọng số', 'Weighted satisfaction score')}</span>
      </div></div>}
      <div className="table-wrap"><table><thead><tr>
        <th>{t('Tiêu chí', 'Criterion')}</th><th>{t('Hài lòng', 'Satisfaction')}</th><th>{t('Quan trọng', 'Importance')}</th>
      </tr></thead><tbody>{rows.map(row => <tr key={row.key}>
        <th scope="row">{row.label}</th><td>{row.satisfaction ?? '—'}</td><td>{row.importance ?? '—'}</td>
      </tr>)}</tbody></table></div>
      <button onClick={() => setSaved(false)}>{t('Sửa lại đánh giá', 'Edit rating')}</button>
    </section>
  }
  const choices: Choice[] = scores.map(score => [score, String(score)])
  const levels: Choice[] = scores.map((score, index) => [score,
    `${score} · ${t(['Rất không hài lòng', 'Không hài lòng', 'Trung lập', 'Hài lòng', 'Rất hài lòng'][index],
      ['Very dissatisfied', 'Dissatisfied', 'Neutral', 'Satisfied', 'Very satisfied'][index])}`])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    const nullable = (key: string) => values.get(key) === 'na' || !values.has(key) ? null : Number(values.get(key))
    setBusy(true); setSaved(false); setError(null)
    try {
      const details = await client.send<Detail>(path, {
        criteria: Object.fromEntries(schema.criteria.map(({ key }) => [key, {
          satisfaction: nullable(`sat:${key}`), importance: Number(values.get(`imp:${key}`)),
        }])),
        tradeoffs: Object.fromEntries(schema.tradeoffs.map(({ key }) => [key, Number(values.get(`trade:${key}`))])),
        overall: Number(values.get('overall')), adoption: values.get('adoption'), vs_manual: nullable('vs_manual'),
        nps: Number(values.get('nps')), conflict_clarity: nullable('conflict_clarity'),
        problems: values.getAll('problem'), comment_good: values.get('comment_good'), comment_improve: values.get('comment_improve'),
      }, 'PUT')
      delete form.dataset.dirty
      setInfo({ schema, details }); setSaved(true)
    } catch (error) { setError(error) }
    finally { setBusy(false) }
  }

  return <form onSubmit={submit} className="form-stack rating-form" data-track>
    <div className="metric-grid rating-metrics">
      <div><strong>{metrics.tasks_fully_placed}/{metrics.tasks_total}</strong><span>{t('Việc xếp đủ', 'Tasks scheduled')}</span></div>
      <div><strong>{metrics.on_time_ratio == null ? '—' : `${Math.round(metrics.on_time_ratio * 100)}%`}</strong><span>{t('Đúng hạn', 'On time')}</span></div>
      <div><strong>{metrics.chunks_total}</strong><span>{t('Phiên làm việc', 'Work sessions')}</span></div>
      <div><strong>{metrics.max_day_minutes}′</strong><span>{t('Ngày nặng nhất', 'Busiest day')}</span></div>
    </div>
    <h3>{t('Hài lòng và tầm quan trọng', 'Satisfaction and importance')}</h3>
    {schema.criteria.map((item, index) => <fieldset className="compact form-stack" key={item.key}>
      <legend>{t(item.title, criterionNames[index])}</legend>
      <p>{t(item.question, [
        'The schedule includes the work and time I need this week.',
        'Required and important tasks are prioritized.',
        'Tasks finish on time with room for delays.',
        'Work stays in a small number of focused sessions.',
        'Work and rest are balanced throughout the week.',
        'The schedule respects personal constraints.',
        'I can realistically follow this schedule.',
      ][index])}</p>
      <details><summary>{t('Chỉ số hệ thống', 'Measured values')}</summary>
        <ul className="simple-list">{facts[item.key]?.map(fact => <li key={fact}>{fact}</li>)}</ul></details>
      <div className="form-grid">
        <Select label={t('Mức hài lòng', 'Satisfaction')} name={`sat:${item.key}`} t={t}
          choices={[...levels, ['na', t('Không áp dụng', 'Not applicable')]]}
          initial={rating?.criteria[item.key] ? rating.criteria[item.key].satisfaction ?? 'na' : undefined} />
        <Select label={t('Tầm quan trọng (1 thấp, 5 cao)', 'Importance (1 low, 5 high)')} name={`imp:${item.key}`}
          choices={choices} initial={rating?.criteria[item.key]?.importance} t={t} />
      </div>
    </fieldset>)}
    <h3>{t('Các lựa chọn đánh đổi', 'Trade-offs')}</h3>
    {schema.tradeoffs.map(({ key, a, b }, index) => <fieldset className="compact form-stack" key={key}>
      <legend>{t('Đánh đổi', 'Trade-off')} {index + 1}</legend>
      <p>A · {t(a, ['Fit more work into the week', 'Finish earlier with spare time', 'Keep personal constraints', 'Prioritize important work', 'Keep sessions together'][index])}</p>
      <p>B · {t(b, ['Keep work in fewer sessions', 'Spread work evenly across days', 'Fit more work by adjusting constraints', 'Balance daily workload', 'Finish earlier by splitting sessions'][index])}</p>
      <Select label={t('Bạn ưu tiên bên nào?', 'Which side do you prefer?')} name={`trade:${key}`} t={t}
        choices={[-2, -1, 0, 1, 2].map((value, index) => [value,
          t(schema.tradeoff_labels[value], ['Strongly A', 'Somewhat A', 'Balanced', 'Somewhat B', 'Strongly B'][index])])}
        initial={rating?.tradeoffs[key]} />
    </fieldset>)}
    <h3>{t('Đánh giá chung', 'Overall rating')}</h3>
    <div className="form-grid">
      <Select label={t('Hài lòng chung', 'Overall satisfaction')} name="overall" choices={levels} initial={rating?.overall} t={t} />
      <Select label={t('Bạn sẽ dùng lịch này thế nào?', 'How will you use this schedule?')} name="adoption"
        choices={schema.adoption.map((value, index) => [value,
          t(value, ['Use as is', 'Use with minor edits', 'Needs major edits', 'Will not use'][index])])} initial={rating?.adoption} t={t} />
      <Select label={t('So với tự xếp lịch', 'Compared with planning manually')} name="vs_manual"
        choices={[...scores.map((value, index): Choice => [value,
          t(schema.vs_manual[value], ['Much worse', 'Slightly worse', 'About the same', 'Slightly better', 'Much better'][index])]),
          ['na', t(schema.no_baseline, 'I have never planned my week manually')]]}
        initial={rating ? rating.vs_manual ?? 'na' : undefined} t={t} />
      <Select label={t('Khả năng giới thiệu (0–10)', 'Likelihood to recommend (0–10)')} name="nps"
        choices={Array.from({ length: 11 }, (_, value) => [value, String(value)])} initial={rating?.nps} t={t} />
      {metrics.options_applied > 0 && <Select label={t('Độ dễ hiểu của phương án', 'Clarity of conflict options')}
        name="conflict_clarity" choices={levels} initial={rating?.conflict_clarity ?? undefined} t={t} />}
    </div>
    <fieldset className="compact form-stack"><legend>{t('Vấn đề gặp phải', 'Issues encountered')}</legend>
      {schema.problems.map((problem, index) => <label key={problem} className="check">
        <input name="problem" value={problem} type="checkbox" defaultChecked={rating?.problems.includes(problem)} />
        {t(problem, ['Important tasks are too late', 'Too many short sessions', 'Some days are too busy',
          'Work is too late or too early', 'Personal constraints changed unexpectedly', 'Work removed or shortened',
          'Poorly spaced tasks', 'The schedule is hard to understand', 'No major issues'][index])}
      </label>)}
    </fieldset>
    <label>{t('Điều tốt (không bắt buộc)', 'What worked well (optional)')}
      <textarea name="comment_good" maxLength={600} defaultValue={rating?.comment_good} /></label>
    <label>{t('Điều cần cải thiện (không bắt buộc)', 'What to improve (optional)')}
      <textarea name="comment_improve" maxLength={600} defaultValue={rating?.comment_improve} /></label>
    <ErrorBox error={error} t={t} />
    <button className="primary" disabled={busy}>{rating ? t('Cập nhật đánh giá', 'Update rating') : t('Gửi đánh giá', 'Submit rating')}</button>
  </form>
}
