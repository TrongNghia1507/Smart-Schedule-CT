import { Fragment, useEffect, useRef, useState, type FormEvent } from 'react'
import { ErrorBox, Icon, Issues, Modal, type T } from '../components/ui'
import { API, type Client, type Draft, type Issue, type Lang, type Task } from '../lib/api'
import { dateInWeek } from '../lib/dates'

export type Edit = { fixed: boolean; task?: Task; inline?: boolean; field?: string }
type ImportPreview = { revision: number; valid: number; unknown: string[]; rows: { line: number; issues: Issue[] }[] }
type Change = Record<string, unknown> & { action: string }
export type ChangeDraft = (command: Change) => Promise<Draft>
const weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const taskColors = [
  '#b95175', '#d95177', '#d78078', '#dc4f30', '#e56536', '#df762f', '#e39733', '#ebbd49',
  '#d9c25c', '#bcc44c', '#81aa58', '#439363', '#50ad80', '#409c92', '#499ed0', '#6389df',
  '#858ac2', '#726dc0', '#b09bcb', '#a379af', '#a756b8', '#917166', '#808080', '#a59889',
]

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
  const [color, setColor] = useState(draft.colors[row.id] ?? '#81aa58')
  const [confirmDelete, setConfirmDelete] = useState(false)
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
  async function remove() {
    setBusy(true)
    setError(null)
    try {
      await change({ action: 'delete', task_id: row.id })
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
        <div className="weekday-options">{weekdays.map((day, index) =>
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
      <fieldset className="compact"><legend>{t('Màu trên lịch', 'Calendar color')}</legend>
        <div className="inline color-options">
          {taskColors.map(value => <button key={value} type="button" aria-label={`${t('Màu', 'Color')} ${value}`}
            title={value} aria-pressed={customColor && color === value} style={{ background: value }} onClick={event => {
              event.currentTarget.form!.dataset.dirty = 'true'
              setColor(value); setCustomColor(true)
            }} />)}
        </div>
        <div className="inline">
          <label className="check"><input type="checkbox" checked={customColor} onChange={event => setCustomColor(event.target.checked)} />
            {t('Màu riêng trên lịch', 'Custom calendar color')}</label>
          {customColor && <input type="color" name="color" aria-label={t('Màu công việc', 'Task color')}
            value={color} onChange={event => setColor(event.target.value)} />}
        </div>
      </fieldset>
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
    {confirmDelete ? <div className="notice">
      <p>{t('Xóa công việc này khỏi bản nháp?', 'Delete this task from the draft?')}</p>
      <div className="inline end"><button type="button" onClick={() => setConfirmDelete(false)} disabled={busy}>{t('Quay lại', 'Go back')}</button>
        <button type="button" className="danger" onClick={() => void remove()} disabled={busy}>{t('Xác nhận xóa', 'Confirm deletion')}</button></div>
    </div> : <div className="inline end">
      {row.id && !edit.inline && <button type="button" className="quiet danger" onClick={() => setConfirmDelete(true)} disabled={busy}>
        {t('Xóa việc này', 'Delete this task')}</button>}
      <button type="button" onClick={close} disabled={busy}>{t('Hủy', 'Cancel')}</button>
      <button className="primary" disabled={busy}>{t('Lưu công việc', 'Save task')}</button>
    </div>}
  </form>
  return edit.inline ? editor : <Modal title={row.id ? t('Sửa công việc', 'Edit task') : t('Thêm công việc', 'Add task')}
    onClose={close} busy={busy} t={t}>{editor}</Modal>
}

type Column = { key: string; label: string; choices?: [string, string][]; type?: string; display?: (row: Task) => string }

function CellEditor({ column, row, fixed, change, close, reload, t }: {
  column: Column; row: Task; fixed: boolean; change: ChangeDraft; close: () => void; reload: () => void; t: T
}) {
  const [value, setValue] = useState(row[column.key] ?? '')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const form = useRef<HTMLFormElement>(null)
  useEffect(() => {
    const input = form.current?.querySelector<HTMLInputElement | HTMLSelectElement>('input, select')
    input?.focus()
    if (input instanceof HTMLInputElement && input.type === 'text') input.select()
  }, [])

  async function save() {
    if (pending.current) return
    if (value === (row[column.key] ?? '')) { close(); return }
    pending.current = true
    setBusy(true); setError(null)
    const fields = { ...row, [column.key]: value }
    if (fixed && value.trim() && column.key === 'repeat') fields.one_off_date = ''
    if (fixed && value.trim() && column.key === 'one_off_date') fields.repeat = ''
    try {
      await change({ action: 'task', task_id: row.id, fixed, fields })
      close()
    } catch (failure) {
      setError(failure)
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  const label = `${column.label} · ${row.name}`
  return <form ref={form} className="cell-editor" data-track onSubmit={event => { event.preventDefault(); void save() }}
    onKeyDown={event => {
      if (event.key === 'Escape' && !pending.current) close()
      if (event.key === 'Enter' && event.target instanceof HTMLSelectElement) {
        event.preventDefault()
        void save()
      }
    }}
    onBlur={event => {
      if (!error && !event.currentTarget.contains(event.relatedTarget)) void save()
    }}>
    {column.choices ? <select aria-label={label} value={value} disabled={busy} onChange={event => setValue(event.target.value)}>
      {column.choices.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select> : <input aria-label={label} type={column.type ?? 'text'} value={value} disabled={busy}
      onChange={event => setValue(event.target.value)} />}
    <div className="inline">
      <button className="quiet" type="submit" disabled={busy}>{t('Lưu', 'Save')}</button>
      <button className="quiet" type="button" disabled={busy} onClick={close}>{t('Hủy', 'Cancel')}</button>
    </div>
    <ErrorBox error={error} t={t} reload={() => { close(); reload() }} />
  </form>
}

function TaskTable({ fixed, draft, edit, setEdit, change, reload, lang, t, remove, busy }: {
  fixed: boolean; draft: Draft; edit: Edit | null; setEdit: (edit: Edit | null) => void; change: ChangeDraft
  reload: () => void; lang: Lang; t: T; remove: (id: string) => void; busy: boolean
}) {
  const rows = fixed ? draft.fixed_tasks : draft.deadline_tasks
  const localDays = t('T2,T3,T4,T5,T6,T7,CN', 'Mon,Tue,Wed,Thu,Fri,Sat,Sun').split(',')
  const shortDate = new Intl.DateTimeFormat(lang === 'vi' ? 'vi-VN' : 'en-GB', {
    day: '2-digit', month: '2-digit', timeZone: 'UTC',
  })
  const yesNo: [string, string][] = [['Có', t('Có', 'Yes')], ['Không', t('Không', 'No')]]
  const dateLabel = (value: string) => value ? shortDate.format(new Date(value.slice(0, 10))) : '—'
  const dateTimeLabel = (value: string) => value ? `${dateLabel(value)} · ${value.slice(11, 16)}` : '—'
  const minutesLabel = (value: string) => value ? `${value}′` : '—'
  const clockMinutes = (value: string) => Number(value.slice(0, 2)) * 60 + Number(value.slice(3))
  const fixedDuration = (row: Task) => {
    const minutes = clockMinutes(row.end) - clockMinutes(row.start)
    return minutesLabel(String(minutes < 0 ? minutes + 1440 : minutes))
  }
  const columns: Column[] = [{ key: 'name', label: t('Công việc', 'Task') }, ...(fixed ? [
    { key: 'repeat', label: t('Lặp lại', 'Repeat'), display: (row: Task) =>
      row.repeat.split(',').map(day => localDays[weekdays.indexOf(day)] ?? day).join(', ') || '—' },
    { key: 'start', label: t('Bắt đầu', 'Start') },
    { key: 'end', label: t('Kết thúc', 'End') },
    { key: '_duration', label: t('Thời lượng', 'Duration'), display: fixedDuration },
    { key: 'prep_min', label: t('Chuẩn bị', 'Preparation'), display: (row: Task) => minutesLabel(row.prep_min) },
    { key: 'after_min', label: t('Di chuyển sau', 'Travel after'), display: (row: Task) => minutesLabel(row.after_min) },
    { key: 'removable_when_busy', label: t('Có thể bỏ khi bận', 'Removable when busy'), choices: yesNo },
    { key: 'one_off_date', label: t('Ngày diễn ra', 'Date'), type: 'date', display: (row: Task) => dateLabel(row.one_off_date) },
  ] : [
    { key: 'mandatory', label: t('Bắt buộc', 'Required'), choices: yesNo },
    { key: 'importance', label: t('Quan trọng', 'Importance'), choices: ['1', '2', '3'].map((value): [string, string] => [value, value]) },
    { key: 'deadline', label: t('Hạn chót', 'Deadline'), type: 'datetime-local', display: (row: Task) => dateTimeLabel(row.deadline) },
    { key: 'remaining_min', label: t('Thời lượng', 'Duration'), display: (row: Task) => minutesLabel(row.remaining_min) },
    { key: 'focus', label: t('Tập trung', 'Focus'), choices: [['high', t('Cao', 'High')], ['low', t('Thấp', 'Low')]] as [string, string][] },
    { key: 'buffer_min', label: t('Nghỉ giữa phiên', 'Rest between sessions'), display: (row: Task) => minutesLabel(row.buffer_min) },
    { key: 'earliest_start', label: t('Bắt đầu sớm nhất', 'Earliest start'), type: 'datetime-local', display: (row: Task) => dateTimeLabel(row.earliest_start) },
    { key: 'chunk_min', label: t('Phiên tối thiểu', 'Min. session'), display: (row: Task) => minutesLabel(row.chunk_min) },
    { key: 'chunk_max', label: t('Phiên tối đa', 'Max. session'), display: (row: Task) => minutesLabel(row.chunk_max) },
  ])]
  return <section className="panel">
    <div className="section-head">
      <div className="panel-heading"><span className={fixed ? 'panel-icon mint' : 'panel-icon lavender'}><Icon name={fixed ? 'calendar' : 'clock'} /></span>
        <div><h2>{fixed ? t('Việc cố định', 'Fixed tasks') : t('Việc có hạn chót', 'Deadline tasks')}</h2>
          <span className="muted">{rows.length} {t('công việc', 'tasks')}</span></div>
      </div>
      <button onClick={() => setEdit({ fixed })} disabled={busy || Boolean(edit)}><Icon name="plus" />{t('Thêm việc', 'Add task')}</button>
    </div>
    {rows.length ? <><p className="muted">{t('Chọn một ô để sửa. Nhấn Enter hoặc rời ô để lưu, Escape để hủy.',
      'Select a cell to edit. Press Enter or leave the cell to save, or Escape to cancel.')}</p>
    <div className="table-wrap editable-table" tabIndex={0} role="region" aria-label={fixed ? t('Bảng việc cố định', 'Fixed task table') : t('Bảng việc có hạn chót', 'Deadline task table')}><table>
      <thead><tr>{columns.map(column => <th key={column.key} scope="col">{column.label}</th>)}
        <th><span className="sr-only">{t('Thao tác', 'Actions')}</span></th></tr></thead>
      <tbody>{rows.map(row => <Fragment key={row.id}>
        <tr>
          {columns.map(column => {
            const Cell = column.key === 'name' ? 'th' : 'td'
            const editing = edit?.task?.id === row.id && edit.field === column.key
            const value = column.display?.(row) ?? column.choices?.find(([key]) => key === row[column.key])?.[1] ?? row[column.key] ?? '—'
            return <Cell scope={column.key === 'name' ? 'row' : undefined} className="table-value" key={column.key}>
              {editing ? <CellEditor column={column} row={row} fixed={fixed} change={change} close={() => setEdit(null)} reload={reload} t={t} /> :
                column.key.startsWith('_') ? value : <button className="quiet cell-button" disabled={busy || Boolean(edit)}
                  aria-label={`${t('Sửa', 'Edit')} ${column.label} · ${row.name}${column.key === 'name' ? '' : ` · ${value}`}`}
                  onClick={() => setEdit({ fixed, task: row, field: column.key })}>
                  {fixed && column.key === 'name' && <span className="swatch" style={{ background: draft.colors[row.id] ?? '#187463' }} />}
                  {value || '—'}
                </button>}
            </Cell>
          })}
          <td className="row-actions">
            <button className="quiet" disabled={busy || Boolean(edit)}
              onClick={() => setEdit({ fixed, task: row, inline: true })}>{t('Sửa', 'Edit')}</button>
            <button className="quiet danger" disabled={busy || Boolean(edit)} onClick={() => remove(row.id)}>{t('Xóa', 'Delete')}</button>
          </td>
        </tr>
        {edit?.inline && edit.task?.id === row.id && <tr><td colSpan={columns.length + 1}>
          <TaskEditor key={row.id} edit={edit} draft={draft} change={change} close={() => setEdit(null)} reload={reload} t={t} />
        </td></tr>}
      </Fragment>)}</tbody>
    </table></div></> : <p className="empty">{t('Chưa có công việc.', 'No tasks yet.')}</p>}
  </section>
}

function CsvGuide({ week, t }: { week: string; t: T }) {
  const sunday = dateInWeek(week, 6).split('-').reverse().join('/')
  const rows = [
    [t('Cả hai', 'Both'), 'task_type, name', '—'],
    ['fixed', t('start, end và repeat hoặc one_off_date', 'start, end and either repeat or one_off_date'),
      t('prep_min 0–90 (mặc định 0), after_min 0–60 (0), removable_when_busy Có/Không (Không)',
        'prep_min 0–90 (default 0), after_min 0–60 (0), removable_when_busy Yes/No (No)')],
    ['deadline', 'deadline, remaining_min',
      t('mandatory Có/Không (Có), importance 1–3 (2), focus high/low (high), buffer_min 0–60 chia hết cho 5 (15), earliest_start, chunk_min và chunk_max (high 45/90, low 30/60)',
        'mandatory Yes/No (Yes), importance 1–3 (2), focus high/low (high), buffer_min 0–60 in multiples of 5 (15), earliest_start, chunk_min and chunk_max (high 45/90, low 30/60)')],
  ]
  return <details><summary>{t('Hướng dẫn định dạng CSV', 'CSV format guide')}</summary>
    <p>{t('Dùng một tệp UTF-8 có dòng tiêu đề, phân tách bằng dấu phẩy. Điền fixed hoặc deadline vào task_type. Để trống các cột không áp dụng. Dòng hợp lệ được thêm vào bản nháp.',
      'Use one UTF-8 file with a header row and comma separators. Set task_type to fixed or deadline and leave unrelated columns blank. Valid rows are added to the draft.')}</p>
    <div className="table-wrap"><table><thead><tr>
      <th>{t('Loại', 'Type')}</th><th>{t('Cột bắt buộc', 'Required columns')}</th><th>{t('Cột tùy chọn và mặc định', 'Optional columns and defaults')}</th>
    </tr></thead><tbody>{rows.map(([kind, required, optional]) => <tr key={kind}>
      <th scope="row">{kind}</th><td>{required}</td><td>{optional}</td>
    </tr>)}</tbody></table></div>
    <p>{t('Dùng HH:mm cho giờ, dd/mm/yyyy cho ngày và dd/mm/yyyy HH:mm cho hạn chót hoặc giờ bắt đầu sớm nhất. Giờ kết thúc chấp nhận 24:00.',
      'Use HH:mm for times, dd/mm/yyyy for dates, and dd/mm/yyyy HH:mm for deadlines or earliest starts. End times accept 24:00.')}</p>
    <p>{t('Lặp theo khoảng T2->CN hoặc liệt kê "T2,T4". Đặt ô có dấu phẩy trong dấu nháy kép. Việc một lần để trống repeat và điền one_off_date.',
      'Use a range such as T2->CN or a list such as "T2,T4". Quote cells containing commas. For one-off tasks, leave repeat blank and fill in one_off_date.')}</p>
    <p>{t(`Nhập thời lượng bằng phút. Nếu không có hạn chót cụ thể, dùng ${sunday} 23:59 trong cột deadline cho tuần đang lập lịch.`,
      `Enter durations in minutes. For a task without a specific deadline, put ${sunday} 23:59 in the deadline column for this planning week.`)}</p>
  </details>
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
        <CsvGuide week={settings.week_start} t={t} />
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
    {edit && !edit.inline && !edit.field && <TaskEditor edit={edit} draft={draft} change={change} close={() => setEdit(null)} reload={reload} t={t} />}
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
