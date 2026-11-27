import { useEffect, useState } from 'react'
import { RatingForm } from '../components/RatingForm'
import { confirmDiscard, ErrorBox, type T } from '../components/ui'
import type { Client, HistorySummary, Lang } from '../lib/api'
import { weekLabel } from '../lib/dates'

export function RatingPage({ client, initialRecordId, lang, t }: {
  client: Client; initialRecordId?: string; lang: Lang; t: T
}) {
  const [records, setRecords] = useState<HistorySummary[] | null>(null)
  const [selected, setSelected] = useState(initialRecordId ?? '')
  const [opened, setOpened] = useState(initialRecordId ?? '')
  const [error, setError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)
  const record = records?.find(item => item.id === selected) ?? records?.[0]
  const savedScheduleLabel = t('Lịch đã lưu', 'Saved schedule')

  useEffect(() => {
    let active = true
    client.get<HistorySummary[]>('/history').then(list => { if (active) setRecords(list) })
      .catch(failure => { if (active) setError(failure) })
    return () => { active = false }
  }, [client, attempt])

  return <>
    <div className="page-heading"><h1>{t('Đánh giá lịch', 'Rate schedule')}</h1></div>
    <section className="panel">
      {error ? <>
        <ErrorBox error={error} t={t} />
        <button onClick={() => { setError(null); setAttempt(value => value + 1) }}>{t('Thử lại', 'Retry')}</button>
      </> : !records ? <p role="status">{t('Đang tải…', 'Loading…')}</p> : record ?
        <div className="section-head">
          <label>{savedScheduleLabel}
            <select aria-label={savedScheduleLabel} value={record.id} onChange={event => {
              if (!confirmDiscard(document, t)) return
              setSelected(event.target.value)
              setOpened('')
            }}>
              {records.map(item => <option key={item.id} value={item.id}>
                {(lang === 'vi' && item.title) ||
                  `${weekLabel(item.week_start, lang)} · ${t('Phiên bản', 'Version')} ${item.version ?? '—'}`}
              </option>)}
            </select>
          </label>
          {opened !== record.id && <button className="primary" onClick={() => setOpened(record.id)}>
            {t('Đánh giá lịch này', 'Rate this schedule')}</button>}
        </div> : <p className="empty">{t('Hãy lưu một lịch để có thể đánh giá.', 'Save a schedule to rate it.')}</p>}
    </section>
    {record && opened === record.id && <section className="panel">
      <SavedScheduleRating key={record.id} recordId={record.id} client={client} t={t} />
    </section>}
  </>
}

function SavedScheduleRating({ recordId, client, t }: { recordId: string; client: Client; t: T }) {
  const [key, setKey] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    client.send<{ schedule_key: string }>(`/history/${encodeURIComponent(recordId)}/rating`)
      .then(result => { if (active) setKey(result.schedule_key) })
      .catch(failure => { if (active) setError(failure) })
    return () => { active = false }
  }, [client, recordId, attempt])

  if (key) return <RatingForm client={client} ratingKey={key} t={t} />
  return error ? <>
    <ErrorBox error={error} t={t} />
    <button onClick={() => { setError(null); setAttempt(value => value + 1) }}>{t('Thử lại', 'Retry')}</button>
  </> : <p role="status">{t('Đang tải đánh giá…', 'Loading rating…')}</p>
}
