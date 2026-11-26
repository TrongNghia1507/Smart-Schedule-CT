import { useEffect, useState } from 'react'
import { blockType, Calendar } from '../components/Calendar'
import { ErrorBox, Modal, type T } from '../components/ui'
import { API, type Client, type Draft, type HistoryDetail, type HistorySummary, type Lang } from '../lib/api'
import { weekLabel } from '../lib/dates'

export function HistoryPage({ client, draft, onRestore, reload, lang, t }: {
  client: Client; draft: Draft; onRestore: (draft: Draft) => void; reload: () => void; lang: Lang; t: T
}) {
  const [records, setRecords] = useState<HistorySummary[] | null>(null)
  const [week, setWeek] = useState('')
  const [selected, setSelected] = useState('')
  const [detail, setDetail] = useState<HistoryDetail | null>(null)
  const [confirm, setConfirm] = useState<'delete' | 'restore' | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const recordId = selected || records?.find(record => !week || record.week_start === week)?.id || ''
  const shown = detail?.record.id === recordId ? detail : null
  const unscheduled = Object.entries(shown?.record.result.unscheduled ?? {})
  const names = new Map(shown?.record.context.tasks.map(task => [task.id, task.name]))
  const recordUrl = `/history/${encodeURIComponent(recordId)}`

  useEffect(() => {
    let alive = true
    client.get<HistorySummary[]>('/history').then(list => { if (alive) setRecords(list) })
      .catch(error => { if (alive) setError(error) })
    return () => { alive = false }
  }, [client])
  useEffect(() => {
    if (!recordId) return
    let alive = true
    client.get<HistoryDetail>(`${recordUrl}?lang=${lang}`).then(data => { if (alive) setDetail(data) })
      .catch(error => { if (alive) setError(error) })
    return () => { alive = false }
  }, [client, recordId, recordUrl, lang])

  async function commit() {
    setBusy(true); setError(null)
    try {
      if (confirm === 'restore') {
        const restored = await client.send<Draft>(recordUrl + '/restore', { expected_revision: draft.revision })
        onRestore(restored)
      } else {
        await client.send(recordUrl, undefined, 'DELETE')
        setRecords(records?.filter(record => record.id !== recordId) ?? [])
        setSelected('')
      }
      setConfirm(null)
    } catch (error) { setError(error) }
    finally { setBusy(false) }
  }

  const weeks = [...new Set(records?.map(record => record.week_start))]
  const formattedTime = (value: string) => new Date(value).toLocaleString(lang === 'vi' ? 'vi-VN' : 'en-GB', {
    timeZone: 'Asia/Ho_Chi_Minh',
  })

  return <>
    <div className="page-heading"><div><h1>{t('Lịch sử', 'History')}</h1>
      <p>{t('Mở, tải hoặc dùng lại một phiên bản lịch đã lưu.', 'Open, download, or reuse a saved schedule version.')}</p></div></div>
    <ErrorBox error={error} t={t} reload={() => { setError(null); reload() }} />
    <section className="panel">
      {!records ? <p role="status">{t('Đang tải…', 'Loading…')}</p> : !records.length ?
        <p className="empty">{t('Chưa có lịch được lưu.', 'No saved schedules yet.')}</p> :
        <div className="form-grid">
          <label>{t('Tuần', 'Week')}<select value={week} onChange={event => { setWeek(event.target.value); setSelected('') }}>
            <option value="">{t('Tất cả các tuần', 'All weeks')}</option>
            {weeks.map(value => <option value={value} key={value}>{weekLabel(value, lang)}</option>)}
          </select></label>
          <label>{t('Phiên bản', 'Version')}<select value={recordId} onChange={event => setSelected(event.target.value)}>
            {!recordId && <option value="">{t('Chưa có phiên bản', 'No versions')}</option>}
            {records.filter(record => !week || record.week_start === week).map(record => <option value={record.id} key={record.id}>
              {(lang === 'vi' && record.title) || `${weekLabel(record.week_start, lang)} · ${t('Phiên bản', 'Version')} ${record.version ?? '—'}`}
              {' · '}{formattedTime(record.saved_at)}
            </option>)}
          </select></label>
        </div>}
    </section>
    {shown && <section className="panel calendar-panel">
      <div className="section-head"><div><h2>{(lang === 'vi' && shown.record.title) || weekLabel(shown.record.week_start, lang)}</h2>
        <p className="muted">{t('Đã lưu', 'Saved')} · {formattedTime(shown.record.saved_at)}</p></div>
        <div className="inline">
          <a className="button" href={API + recordUrl + '/export'}>{t('Tải JSON', 'Download JSON')}</a>
          <button onClick={() => setConfirm('restore')}>{t('Dùng làm bản nháp', 'Restore as draft')}</button>
          <button className="danger" onClick={() => setConfirm('delete')}>{t('Xóa phiên bản', 'Delete version')}</button>
        </div>
      </div>
      {lang === 'vi' && shown.record.description && <p>{shown.record.description}</p>}
      {unscheduled.length > 0 ? <div className="notice"><strong>{t('Việc chưa xếp trong phiên bản này', 'Tasks left unscheduled in this version')}</strong>
        <ul className="simple-list">{unscheduled.map(([id, minutes]) => <li key={id}>{names.get(id) ?? id} ({minutes}′)</li>)}</ul>
      </div> : <p className="muted">{shown.record.complete ? t('Đã xếp đủ việc.', 'All tasks scheduled.') :
        t('Vẫn còn việc chưa xếp.', 'Some tasks remain unscheduled.')}</p>}
      <Calendar events={shown.events} week={shown.record.week_start} lang={lang} t={t} />
      <details><summary>{t('Bảng chi tiết theo thời gian', 'Schedule details by time')}</summary>
        <div className="table-wrap"><table><thead><tr><th>{t('Công việc', 'Task')}</th><th>{t('Loại', 'Type')}</th>
          <th>{t('Bắt đầu', 'Start')}</th><th>{t('Kết thúc', 'End')}</th></tr></thead>
          <tbody>{shown.entries.map((entry, index) => <tr key={index}>
            <th scope="row">{entry.name}</th><td>{blockType(entry.kind, t)}</td>
            <td>{entry.start.replace('T', ' ')}</td><td>{entry.end.replace('T', ' ')}</td></tr>)}</tbody>
        </table></div>
      </details>
    </section>}
    {confirm && <Modal title={confirm === 'delete' ? t('Xóa phiên bản lịch', 'Delete schedule version') :
      t('Khôi phục dữ liệu nhập', 'Restore task input')} onClose={() => setConfirm(null)} busy={busy} t={t}>
      <p>{confirm === 'delete' ? t('Xóa phiên bản lịch đang chọn?', 'Delete the selected schedule version?') :
        t('Dùng dữ liệu của lịch đã lưu để thay thế bản nháp hiện tại?', 'Replace the current draft with input from this saved schedule?')}</p>
      <ErrorBox error={error} t={t} reload={() => { setError(null); reload() }} />
      <div className="inline end"><button onClick={() => setConfirm(null)} disabled={busy}>{t('Hủy', 'Cancel')}</button>
        <button className="primary" disabled={busy} onClick={() => void commit()}>{t('Xác nhận', 'Confirm')}</button></div>
    </Modal>}
  </>
}
