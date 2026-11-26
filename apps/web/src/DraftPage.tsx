import { Fragment, useState, type FormEvent } from 'react'
import { API, type Client, type Draft, type Issue, type Lang, type Task } from './api'
import { dateInWeek } from './dates'
import { ErrorBox, Icon, Issues, Modal, type T } from './ui'

export type Edit = { fixed: boolean; task?: Task; inline?: boolean }
type ImportPreview = { revision: number; valid: number; unknown: string[]; rows: { line: number; issues: Issue[] }[] }
type Change = Record<string, unknown> & { action: string }
export type ChangeDraft = (command: Change) => Promise<Draft>

function taskFields(form: HTMLFormElement, fixed: boolean, repeated: boolean, endOfWeek: string | null) {
  const values = new FormData(form)
  const { color, ...fields } = Object.fromEntries(values)
  if (fixed) {
    fields.repeat = repeated ? values.getAll('day').join(',') : ''
    fields.one_off_date = repeated ? '' : fields.one_off_date ?? ''
    delete fields.day
  }
  if (!fixed && endOfWeek) fields.deadline = endOfWeek
  return { fields, ...(fixed && { color: color ? String(color) : null }) }
}

export function TaskEditor({ edit, draft, change, close, reload, t }: {
  edit: Edit; draft: Draft; change: ChangeDraft; close: () => void; reload: () => void; t: T
}) {
  const row = edit.task ?? {}
  const fixed = edit.fixed
  const endOfWeek = `${dateInWeek(draft.settings.week_start, 6)}T23:59`
  const [freeDeadline, setFreeDeadline] = useState(row.deadline === endOfWeek)
  const [repeated, repeat] = useState(!row.one_off_date)
  const [customColor, setCustomColor] = useState(Boolean(draft.colors[row.id]))
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [focus, setFocus] = useState(row.focus || 'high')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    setBusy(true)
    setError(null)
    try {
      await change({ action: 'task', task_id: row.id ?? null, fixed, ...taskFields(form, fixed, repeated, freeDeadline ? endOfWeek : null) })
      delete form.dataset.dirty
      close()
    } catch (failure) {
      setError(failure)
    } finally {
      setBusy(false)
    }
  }
  const yesNo = (name: string, label: string, defaultValue: string) =>
    <label>{label}<select name={name} defaultValue={row[name] ?? defaultValue}>
      <option value="Có">{t('Có', 'Yes')}</option><option value="Không">{t('Không', 'No')}</option>
    </select></label>
  const minutes = (name: string, label: string, defaultValue?: number, min = 0, max?: number, step = 1) =>
    <label>{label}<input name={name} type="number" min={min} max={max} step={step}
      defaultValue={row[name] ?? defaultValue} required={name === 'remaining_min'} /></label>
  const editor = <form className="form-stack task-editor" data-track onSubmit={submit}>
    <label>{t('Tên công việc', 'Task name')}<input name="name" defaultValue={row.name} maxLength={100} required /></label>
    {fixed ? <>
      <div className="form-grid">
        <label>{t('Bắt đầu', 'Start')}<input name="start" placeholder="08:00" defaultValue={row.start} required /></label>
        <label>{t('Kết thúc', 'End')}<input name="end" placeholder="09:00" defaultValue={row.end} required /></label>
      </div>
      <label>{t('Lặp lại', 'Recurrence')}<select value={repeated ? 'week' : 'once'} onChange={event => repeat(event.target.value === 'week')}>
        <option value="week">{t('Hằng tuần', 'Weekly')}</option><option value="once">{t('Một lần', 'Once')}</option>
      </select></label>
      {repeated ? <fieldset className="compact"><legend>{t('Các ngày trong tuần', 'Days of the week')}</legend>
        <div className="weekday-options">{['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map((day, index) =>
          <label className="check" key={day}><input name="day" type="checkbox" value={day}
            defaultChecked={(row.repeat ?? 'mon').split(',').includes(day)} />
            {t(['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'][index], ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][index])}
          </label>)}</div></fieldset> :
        <label>{t('Ngày diễn ra', 'Date')}<input name="one_off_date" type="date" defaultValue={row.one_off_date || draft.settings.week_start} required /></label>}
      <div className="form-grid">
        {minutes('prep_min', t('Chuẩn bị (phút)', 'Preparation (minutes)'), 0, 0, 90)}
        {minutes('after_min', t('Di chuyển sau (phút)', 'Travel after (minutes)'), 0, 0, 60)}
        {yesNo('removable_when_busy', t('Có thể bỏ khi bận', 'Removable when busy'), 'Không')}
      </div>
      <div className="inline">
        <label className="check"><input type="checkbox" checked={customColor} onChange={event => setCustomColor(event.target.checked)} />
          {t('Màu riêng trên lịch', 'Custom calendar color')}</label>
        {customColor && <input type="color" name="color" aria-label={t('Màu công việc', 'Task color')}
          defaultValue={draft.colors[row.id] ?? '#81aa58'} />}
      </div>
    </> : <>
      <label className="check deadline-toggle"><input type="checkbox" checked={freeDeadline}
        onChange={event => setFreeDeadline(event.target.checked)} />
        <span>{t('Không có hạn chót cụ thể', 'No specific deadline')}
          <small>{t('Dùng 23:59 Chủ nhật của tuần lập lịch.', 'Uses Sunday at 23:59 of the planning week.')}</small></span>
      </label>
      <div className="form-grid">
        <label hidden={freeDeadline}>{t('Hạn chót', 'Deadline')}<input name="deadline" type="datetime-local"
          defaultValue={row.deadline} required={!freeDeadline} disabled={freeDeadline} /></label>
        <label>{t('Thời lượng (phút)', 'Duration (minutes)')}<input name="remaining_min"
          placeholder={t('Ví dụ 60 hoặc 1h30', 'For example, 60 or 1h30')} defaultValue={row.remaining_min} maxLength={24} required /></label>
        {minutes('buffer_min', t('Nghỉ giữa phiên (phút)', 'Break after session (minutes)'), 15, 0, 60, 5)}
      </div>
      <div className="form-grid">
        {yesNo('mandatory', t('Bắt buộc', 'Required'), 'Có')}
        <label>{t('Mức quan trọng', 'Importance')}<select name="importance" defaultValue={row.importance ?? '2'}>
          <option value="1">{t('1 · Thấp', '1 · Low')}</option><option value="2">{t('2 · Vừa', '2 · Medium')}</option>
          <option value="3">{t('3 · Cao', '3 · High')}</option>
        </select></label>
        <label>{t('Độ tập trung', 'Focus')}<select name="focus" value={focus} onChange={event => setFocus(event.target.value)}>
          <option value="high">{t('Cao', 'High')}</option><option value="low">{t('Thấp', 'Low')}</option>
        </select></label>
      </div>
      <details className="advanced-fields" open={Boolean(row.earliest_start)}>
        <summary>{t('Tùy chọn nâng cao', 'Advanced settings')}</summary>
        <div className="form-grid">
          <label>{t('Bắt đầu sớm nhất', 'Earliest start')}<input name="earliest_start" type="datetime-local" defaultValue={row.earliest_start} /></label>
          {minutes('chunk_min', t('Phiên tối thiểu (phút)', 'Min. session (minutes)'), undefined, 1)}
          {minutes('chunk_max', t('Phiên tối đa (phút)', 'Max. session (minutes)'), undefined, 1)}
        </div>
        {!row.id && <p className="muted">{t('Để trống độ dài phiên để dùng mặc định theo độ tập trung.',
          'Leave session lengths blank to use the defaults for the selected focus level.')}</p>}
      </details>
    </>}
    <ErrorBox error={error} t={t} reload={() => { close(); reload() }} />
    <div className="inline end"><button type="button" onClick={close} disabled={busy}>{t('Hủy', 'Cancel')}</button>
      <button className="primary" disabled={busy}>{t('Lưu công việc', 'Save task')}</button></div>
  </form>
  return edit.inline ? editor : <Modal title={row.id ? t('Sửa công việc', 'Edit task') : t('Thêm công việc', 'Add task')}
    onClose={close} busy={busy} t={t}>{editor}</Modal>
}

function TaskTable({ fixed, draft, edit, setEdit, change, reload, lang, t, remove, busy }: {
  fixed: boolean; draft: Draft; edit: Edit | null; setEdit: (edit: Edit | null) => void; change: ChangeDraft
  reload: () => void; lang: Lang; t: T; remove: (id: string) => void; busy: boolean
}) {
  const rows = fixed ? draft.fixed_tasks : draft.deadline_tasks
  const fields = fixed ? [t('Ngày', 'Days'), t('Khung giờ', 'Time'), t('Chuẩn bị / sau', 'Prep / after')] :
    [t('Hạn chót', 'Deadline'), t('Thời lượng', 'Duration'), t('Quan trọng', 'Importance')]
  const weekdays = t('T2,T3,T4,T5,T6,T7,CN', 'Mon,Tue,Wed,Thu,Fri,Sat,Sun').split(',')
  const shortDate = new Intl.DateTimeFormat(lang === 'vi' ? 'vi-VN' : 'en-GB', {
    day: '2-digit', month: '2-digit', timeZone: 'UTC',
  })
  const daysLabel = (task: Task) => task.repeat ? task.repeat.split(',').map(day =>
    weekdays[['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].indexOf(day)] ?? day).join(', ') :
    shortDate.format(new Date(task.one_off_date))
  return <section className="panel">
    <div className="section-head">
      <div className="panel-heading"><span className={fixed ? 'panel-icon mint' : 'panel-icon lavender'}><Icon name={fixed ? 'calendar' : 'clock'} /></span>
        <div><h2>{fixed ? t('Việc cố định', 'Fixed tasks') : t('Việc có hạn chót', 'Deadline tasks')}</h2>
          <span className="muted">{rows.length} {t('công việc', 'tasks')}</span></div>
      </div>
      <button onClick={() => setEdit({ fixed })} disabled={busy}><Icon name="plus" />{t('Thêm việc', 'Add task')}</button>
    </div>
    {rows.length ? <div className="table-wrap"><table>
      <thead><tr><th>{t('Công việc', 'Task')}</th>{fields.map(label => <th key={label}>{label}</th>)}
        <th><span className="sr-only">{t('Thao tác', 'Actions')}</span></th></tr></thead>
      <tbody>{rows.map(row => <Fragment key={row.id}>
        <tr>
          <th scope="row">{fixed && <span className="swatch" style={{ background: draft.colors[row.id] ?? '#187463' }} />}{row.name}</th>
          {(fixed ? [daysLabel(row), `${row.start}–${row.end}`, `${row.prep_min} / ${row.after_min}′`] :
            [`${shortDate.format(new Date(row.deadline.slice(0, 10)))} · ${row.deadline.slice(11, 16)}`,
              `${row.remaining_min}′`, `${row.importance}/3`]).map((value, index) => <td className="table-value" key={index}>{value}</td>)}
          <td className="row-actions">
            <button className="quiet" disabled={busy} onClick={() => setEdit({ fixed, task: row, inline: true })}>{t('Sửa', 'Edit')}</button>
            <button className="quiet danger" disabled={busy} onClick={() => remove(row.id)}>{t('Xóa', 'Delete')}</button>
          </td>
        </tr>
        {edit?.inline && edit.task?.id === row.id && <tr><td colSpan={5}>
          <TaskEditor key={row.id} edit={edit} draft={draft} change={change} close={() => setEdit(null)} reload={reload} t={t} />
        </td></tr>}
      </Fragment>)}</tbody>
    </table></div> : <p className="empty">{t('Chưa có công việc.', 'No tasks yet.')}</p>}
  </section>
}

export function DraftPage({ draft, client, change, adopt, reload, advance, lang, t }: {
  draft: Draft; client: Client; change: ChangeDraft; adopt: (draft: Draft) => void; reload: () => void
  advance: () => void; lang: Lang; t: T
}) {
  const [edit, setEdit] = useState<Edit | null>(null)
  const [confirm, setConfirm] = useState<Change | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const { settings } = draft
  const issueCount = draft.issues.filter(issue => issue.severity === 'Error').length

  async function run(command: Change) {
    setBusy(true)
    setError(null)
    try { await change(command); setConfirm(null); setEdit(null) }
    catch (failure) { setError(failure) }
    finally { setBusy(false) }
  }

  async function csv(importing: boolean) {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      if (importing && preview) {
        adopt(await client.upload<Draft>(`/draft/imports?expected_revision=${preview.revision}`, file))
        setFile(null)
        setPreview(null)
      } else {
        setPreview(await client.upload<ImportPreview>('/draft/imports/preview', file))
      }
    } catch (failure) { setError(failure) }
    finally { setBusy(false) }
  }

  return <>
    <div className="page-heading"><div><h1>{t('Nhập dữ liệu', 'Task input')}</h1>
      <p>{t('Chọn tuần, thêm công việc và kiểm tra dữ liệu trước khi xếp lịch.',
        'Choose a week, add tasks, and review your input before scheduling.')}</p></div>
      <button className="primary" onClick={advance} disabled={busy || Boolean(edit) || issueCount > 0}>
        <Icon name="calendar" />{t('Xem trước lịch', 'Preview calendar')}</button>
    </div>
    <div className="draft-stats">
      <div><span className="panel-icon mint"><Icon name="calendar" /></span><div>
        <strong>{draft.fixed_tasks.length}</strong><span>{t('Việc cố định', 'Fixed tasks')}</span></div></div>
      <div><span className="panel-icon lavender"><Icon name="clock" /></span><div>
        <strong>{draft.deadline_tasks.reduce((minutes, task) => minutes + Number(task.remaining_min), 0)}′</strong>
        <span>{t('Tổng thời lượng việc có hạn', 'Deadline workload')}</span></div></div>
      <div><span className={issueCount ? 'panel-icon amber' : 'panel-icon mint'}><Icon name="check" /></span><div>
        <strong>{issueCount ? t(`${issueCount} mục cần sửa`, `${issueCount} to fix`) : t('Sẵn sàng', 'Ready')}</strong>
        <span>{t('Kiểm tra dữ liệu', 'Input validation')}</span></div></div>
    </div>
    <ErrorBox error={error} t={t} reload={() => { setError(null); setPreview(null); setConfirm(null); reload() }} />
    {draft.notes.length > 0 && <div className="notice">{draft.notes.map(note => <p key={note}>{note}</p>)}</div>}
    <section className="panel">
      <div className="section-head"><h2>{t('Thiết lập tuần', 'Week settings')}</h2>
        <div className="inline">
          <button disabled={busy || Boolean(edit)} onClick={() => setConfirm({ action: 'sample' })}>{t('Nạp mẫu', 'Load sample')}</button>
          <button disabled={busy || Boolean(edit) || !draft.can_undo} onClick={() => void run({ action: 'undo' })}>{t('Hoàn tác', 'Undo')}</button>
          <button className="danger" disabled={busy || Boolean(edit) || !(draft.fixed_tasks.length || draft.deadline_tasks.length)}
            onClick={() => setConfirm({ action: 'clear' })}>{t('Xóa toàn bộ', 'Clear all')}</button>
        </div>
      </div>
      <form className="settings-form" data-track key={draft.revision} onSubmit={event => {
        event.preventDefault()
        void run({ ...Object.fromEntries(new FormData(event.currentTarget)), action: 'settings' })
      }}>
        <label>{t('Tuần bắt đầu (Thứ Hai)', 'Week starting (Monday)')}<input name="week_start" type="date" defaultValue={settings.week_start} required /></label>
        <label>{t('Bắt đầu ngủ', 'Sleep starts')}<input name="sleep_start" defaultValue={settings.sleep.start} placeholder="23:00" required /></label>
        <label>{t('Kết thúc ngủ', 'Sleep ends')}<input name="sleep_end" defaultValue={settings.sleep.end} placeholder="05:00" required /></label>
        <button disabled={busy || Boolean(edit)}>{t('Áp dụng', 'Apply')}</button>
      </form>
    </section>
    {([true, false] as const).map(fixed => <TaskTable key={String(fixed)} fixed={fixed} draft={draft} edit={edit}
      setEdit={setEdit} change={change} reload={reload} lang={lang} t={t} busy={busy}
      remove={task_id => setConfirm({ action: 'delete', task_id })} />)}
    <section className="panel">
      <div className="section-head">
        <div className="panel-heading"><span className="panel-icon lavender"><Icon name="files" /></span><h2>CSV</h2></div>
        <div className="inline"><a className="button" href={API + `/draft/example?lang=${lang}`}>{t('Tải CSV mẫu', 'Download sample CSV')}</a>
          <a className="button" href={API + '/draft/export'}>{t('Xuất CSV', 'Export CSV')}</a></div>
      </div>
      <details><summary>{t('Nhập công việc từ CSV', 'Import tasks from CSV')}</summary>
        <p className="muted">{t('Dùng CSV UTF-8 có cột task_type (fixed hoặc deadline). Tải CSV hiện tại để lấy tiêu đề cột.',
          'Use UTF-8 CSV with a task_type column (fixed or deadline). Export the current CSV for the column headers.')}</p>
        <div className="inline">
          <input className="file-input" type="file" aria-label={t('Chọn tệp CSV', 'Choose CSV file')} accept=".csv,text/csv"
            disabled={busy} key={file?.name ?? 'empty'} onChange={event => { setPreview(null); setFile(event.target.files?.[0] ?? null) }} />
          <button disabled={!file || busy || Boolean(edit)} onClick={() => void csv(false)}>{t('Kiểm tra CSV', 'Preview CSV')}</button>
        </div>
        {preview && <div className="notice">
          {preview.unknown.length > 0 && <p>{t('Bỏ qua cột', 'Ignored columns')} · {preview.unknown.join(', ')}</p>}
          {preview.rows.filter(row => row.issues.length).map(row => <div key={row.line}>
            <strong>{t('Dòng', 'Row')} {row.line}</strong><Issues issues={row.issues} t={t} />
          </div>)}
          <button className="primary" disabled={busy || !preview.valid || preview.revision !== draft.revision}
            onClick={() => void csv(true)}>{t('Nhập số dòng hợp lệ', 'Import valid rows')} ({preview.valid})</button>
          {preview.revision !== draft.revision && <p>{t('Bản nháp đã đổi. Hãy kiểm tra lại tệp.', 'The draft has changed. Preview the file again.')}</p>}
        </div>}
      </details>
    </section>
    {draft.issues.length > 0 && <section className="panel"><details open={draft.issues.some(issue => issue.severity === 'Error')}>
      <summary>{t('Kiểm tra dữ liệu', 'Input validation')} ({draft.issues.length})</summary><Issues issues={draft.issues} t={t} />
    </details></section>}
    {edit && !edit.inline && <TaskEditor edit={edit} draft={draft} change={change} close={() => setEdit(null)} reload={reload} t={t} />}
    {confirm && <Modal title={t('Xác nhận thay đổi', 'Confirm change')} onClose={() => setConfirm(null)} busy={busy} t={t}>
      <p>{confirm.action === 'sample' ? t('Nạp mẫu sẽ thay toàn bộ công việc và chuyển sang tuần tới.',
        'Loading the sample replaces all tasks and switches to next week.') : confirm.action === 'clear' ?
        t('Xóa toàn bộ công việc trong bản nháp?', 'Clear all tasks from this draft?') :
        t('Xóa công việc này khỏi bản nháp?', 'Delete this task from the draft?')}</p>
      <ErrorBox error={error} t={t} reload={() => { setError(null); setConfirm(null); reload() }} />
      <div className="inline end"><button onClick={() => setConfirm(null)} disabled={busy}>{t('Hủy', 'Cancel')}</button>
        <button className="primary" onClick={() => void run(confirm)} disabled={busy}>{t('Xác nhận', 'Confirm')}</button></div>
    </Modal>}
  </>
}
