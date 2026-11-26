import { useEffect, useRef, useState } from 'react'
import type { EventApi, EventDropArg } from '@fullcalendar/core'
import { blockType, Calendar } from '../components/Calendar'
import { RatingForm } from '../components/RatingForm'
import { ErrorBox, Icon, Issues, Modal, type T } from '../components/ui'
import { API, type Client, type Draft, type Lang, type Option, type Plan, type Preview } from '../lib/api'
import { currentMonday, weekLabel } from '../lib/dates'
import { TaskEditor, type ChangeDraft, type Edit } from './DraftPage'

const optionTitle = (id: number, t: T) => [
  t('Bỏ việc khỏi tuần', 'Remove task from the week'),
  t('Giảm thời lượng', 'Reduce duration'),
  t('Nới ràng buộc', 'Relax constraints'),
][id - 1]

function ConflictOption({ option, week, lang, t, busy, apply }: {
  option: Option; week: string; lang: Lang; t: T; busy: boolean
  apply: (id: number, duration?: number) => void
}) {
  const [duration, setDuration] = useState(option.maximum ?? 0)
  const [previewOpen, setPreviewOpen] = useState(false)
  return <article className="option">
    <h3>{optionTitle(option.id, t)}</h3>
    <ul className="simple-list">{option.descriptions.map(text => <li key={text}>{text}</li>)}</ul>
    {option.explanation && <p className="muted">{option.explanation}</p>}
    {option.warnings.map(warning => <p className="muted" key={warning}>{warning}</p>)}
    {option.unplaced.length > 0 && <p className="muted">{t('Vẫn chưa xếp', 'Still unplaced')} · {option.unplaced.map(
      task => `${task.name} (${task.minutes}′)`).join(', ')}</p>}
    {option.available && <details onToggle={event => setPreviewOpen(event.currentTarget.open)}>
      <summary>{t('Xem lịch theo phương án', 'Preview this option')}</summary>
      {previewOpen && <Calendar compact events={option.events} week={week} lang={lang} t={t} />}
    </details>}
    {option.available && <form className="inline" onSubmit={event => {
      event.preventDefault()
      if (option.id !== 1 || window.confirm(t('Bỏ việc này khỏi kế hoạch tuần?', 'Remove this task from the weekly plan?'))) {
        apply(option.id, option.id === 2 ? duration : undefined)
      }
    }}>
      {option.id === 2 && <label>{t('Thời lượng mới (phút)', 'New duration (minutes)')}
        <input type="number" min={option.minimum ?? 1} max={option.maximum ?? undefined}
          required value={duration || ''} onChange={event => setDuration(+event.target.value)} /></label>}
      <button className="primary" disabled={busy}>{t('Áp dụng', 'Apply')}</button>
    </form>}
    {option.available && option.id === 2 && duration !== option.maximum && <p className="muted">
      {t(`Lịch xem thử dùng mức đã kiểm chứng ${option.maximum} phút. Hệ thống sẽ kiểm tra mức bạn nhập khi áp dụng.`,
        `The preview uses the verified duration of ${option.maximum} minutes. The duration you enter is checked when you apply.`)}
    </p>}
  </article>
}

function operationId() {
  const data = crypto.getRandomValues(new Uint8Array(16))
  data[6] = (data[6] & 15) | 64
  data[8] = (data[8] & 63) | 128
  const hex = Array.from(data, value => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function PlannerPage({ client, draft, change, reload, toInput, lang, t }: {
  client: Client; draft: Draft; change: ChangeDraft; reload: () => void; toInput: () => void; lang: Lang; t: T
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [currentWeek, setCurrentWeek] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [showPlan, setShowPlan] = useState(true)
  const [edit, setEdit] = useState<Edit | null>(null)
  const [selected, setSelected] = useState<EventApi | null>(null)
  const [target, setTarget] = useState('')
  const [earlier, setEarlier] = useState(0)
  const [later, setLater] = useState(0)
  const [ratingKey, setRatingKey] = useState<string | null>(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [refreshCount, refreshResources] = useState(0)
  const pendingOperations = useRef(new Map<string, string>())

  useEffect(() => {
    let active = true
    client.get<Preview>(`/draft/preview?current_week=${currentWeek}`)
      .then(result => { if (active) setPreview(result) }).catch(error => { if (active) setError(error) })
    return () => { active = false }
  }, [client, draft.revision, currentWeek, refreshCount])

  useEffect(() => {
    let active = true
    client.get<Plan | null>(`/plans/latest?lang=${lang}`).then(result => {
      if (active) {
        setPlan(result)
        if (result) { setEarlier(result.earlier); setLater(result.later) }
      }
    }).catch(error => { if (active) setError(error) })
    return () => { active = false }
  }, [client, draft.revision, lang, refreshCount])

  const activePlan = plan?.draft_revision === draft.revision ? plan : null
  const visiblePlan = showPlan && !currentWeek ? activePlan : null
  const shownPreview = preview?.revision === draft.revision ? preview : null
  const week = visiblePlan?.week_start ?? shownPreview?.week_start ?? draft.settings.week_start
  const calendarMode = currentWeek ? 'now' : visiblePlan ? 'plan' : 'draft'
  const targetId = activePlan?.unscheduled.some(task => task.id === target) ? target : activePlan?.unscheduled[0]?.id ?? ''
  const report = activePlan?.reports[targetId]
  const errors = draft.issues.some(issue => issue.severity === 'Error')

  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(null); setStatus('')
    try { await action() }
    catch (failure) { setError(failure) }
    finally { setBusy(false) }
  }

  async function sendOperation<T>(path: string, body: object) {
    const key = path + JSON.stringify(body)
    const id = pendingOperations.current.get(key) ?? operationId()
    pendingOperations.current.set(key, id)
    const result = await client.send<T>(path, { ...body, operation_id: id })
    pendingOperations.current.delete(key)
    return result
  }

  function runPlan() {
    void perform(async () => {
      const next = await sendOperation<Plan>(`/plans?lang=${lang}`, { expected_revision: draft.revision, earlier, later })
      setPlan(next); setShowPlan(true); setCurrentWeek(false)
    })
  }

  function analyze() {
    if (!activePlan || !targetId) return
    void perform(async () => setPlan(await client.send<Plan>(`/plans/${activePlan.id}/conflicts?lang=${lang}`, {
      expected_version: activePlan.version, task_id: targetId,
    })))
  }

  function apply(id: number, duration?: number) {
    if (!activePlan) return
    void perform(async () => {
      setPlan(await sendOperation<Plan>(`/plans/${activePlan.id}/apply?lang=${lang}`, {
        expected_version: activePlan.version, task_id: targetId, option_id: id, duration,
      }))
      setStatus(t('Đã áp dụng phương án. Bấm Lưu vào lịch sử để giữ phiên bản.', 'Option applied. Use Save to history to keep this version.'))
    })
  }

  function move(event: EventDropArg) {
    if (busy || !shownPreview) { event.revert(); return }
    void perform(async () => {
      try {
        await change({ action: 'move', task_id: event.event.extendedProps.task_id,
          old_start: event.oldEvent.startStr.slice(0, 19), new_start: event.event.startStr.slice(0, 19), current_week: currentWeek })
      } catch (failure) { event.revert(); throw failure }
    })
  }

  function showEvent(event: EventApi) {
    if (busy) return
    const task = draft.fixed_tasks.find(task => task.id === event.extendedProps.task_id)
    if (task && !visiblePlan && event.extendedProps.kind === 'fixed') {
      setEdit({ fixed: true, task })
    } else if (event.title && event.extendedProps.kind !== 'sleep') {
      setSelected(event)
    }
  }

  async function finalize(download: boolean) {
    if (!activePlan) return
    await perform(async () => {
      const path = `/plans/${activePlan.id}`
      const data = { expected_version: activePlan.version }
      const { schedule_key } = await client.send<{ schedule_key: string }>(path + '/finalize', data)
      setPlan({ ...activePlan, schedule_key })
      setRatingKey(schedule_key)
      if (download) await client.download(path + '/download', data)
    })
  }

  function refresh() {
    setError(null)
    setEdit(null)
    refreshResources(count => count + 1)
    reload()
  }

  const eventTask = selected && [...draft.fixed_tasks, ...draft.deadline_tasks].find(task => task.id === selected.extendedProps.task_id)
  const deadline = selected && visiblePlan?.deadline_details[selected.extendedProps.task_id]
  const duration = selected?.start && selected.end ? (selected.end.getTime() - selected.start.getTime()) / 60000 : null
  const shownEvents = visiblePlan?.events ?? shownPreview?.events ?? []
  const moveEvent = visiblePlan || busy || !shownPreview ? undefined : move
  return <>
    <div className="page-heading calendar-heading"><div><h1>{t('Lịch tuần', 'Weekly calendar')}</h1>
      <p className="date-label"><Icon name="calendar" />{weekLabel(week, lang)}</p></div>
      <button onClick={toInput}><Icon name="list" />{t('Về nhập dữ liệu', 'Back to input')}</button>
    </div>
    <ErrorBox error={error} t={t} reload={refresh} />
    {status && <p className="notice" role="status">{status}</p>}
    <div className="planner-layout">
      <section className="panel calendar-panel">
        <div className="section-head">
          <div className="panel-heading"><span className="panel-icon mint"><Icon name="calendar" /></span>
            <h2>{visiblePlan ? t('Lịch đã xếp', 'Scheduled week') : t('Xem trước', 'Week preview')}</h2></div>
          <div className="inline">
            {activePlan && !currentWeek && <button onClick={() => setShowPlan(value => !value)} disabled={busy}>
              {visiblePlan ? t('Xem bản nháp', 'Show draft') : t('Xem lịch đã xếp', 'Show schedule')}</button>}
            <button onClick={() => { setPreview(null); setCurrentWeek(value => !value) }} disabled={busy}>{currentWeek ?
              t('Tuần lập lịch', 'Planning week') : t('Tuần hiện tại', 'Current week')}</button>
            <button onClick={() => setExpanded(true)}>{t('Phóng to', 'Expand')}</button>
          </div>
        </div>
        {currentWeek && <p className="muted">{t('Đang xem tuần hiện tại. Việc chuyển chế độ xem giữ nguyên tuần lập lịch.',
          'Viewing the current week. Changing the view leaves the planning week in place.')}</p>}
        {!currentWeek && week !== currentMonday() && <p className="muted">{t('Vạch giờ hiện tại chỉ hiện trong tuần có ngày hôm nay.',
          'The current-time marker appears in the week that contains today.')}</p>}
        {visiblePlan || shownPreview ? <Calendar events={shownEvents} week={week} lang={lang} t={t} mode={calendarMode}
          onEvent={showEvent} onDrop={moveEvent} /> :
          <p role="status">{t('Đang tải lịch…', 'Loading calendar…')}</p>}
        <div className="calendar-legend">
          <span><i className={visiblePlan ? 'swatch planned-fixed' : 'swatch fixed'} />{t('Việc cố định', 'Fixed tasks')}</span>
          {visiblePlan && <span><i className="swatch deadline" />{t('Việc có hạn chót', 'Deadline tasks')}</span>}
          <span><i className="swatch sleep" />{t('Giờ ngủ', 'Sleep')} {!visiblePlan && <>{draft.settings.sleep.start}–{draft.settings.sleep.end}</>}</span>
          <span><i className="swatch current-time" />{t('Giờ hiện tại', 'Current time')}</span>
        </div>
        <p className="muted">{visiblePlan ? t('Bấm vào khối để xem chi tiết. Màu việc có hạn chót đậm dần theo mức quan trọng 1–3.',
          'Select a block for details. Deadline task color intensifies with importance from 1 to 3.') :
          t('Bấm để sửa việc cố định hoặc kéo theo bước 10 phút. Nếu việc lặp lại, thay đổi áp dụng cho cả chuỗi.',
            'Select a fixed task to edit or drag it in 10-minute steps. A move changes the entire recurring series.')}</p>
      </section>
      <aside className="planner-aside">
        <section className="panel"><h2>{t('Tóm tắt lịch', 'Calendar summary')}</h2>
          {visiblePlan ? <p>{shownEvents.filter(event => event.extendedProps?.kind === 'deadline').length} {t('khối deadline đã xếp', 'scheduled deadline blocks')}</p> :
            <><p>{draft.fixed_tasks.length} {t('việc cố định', 'fixed tasks')}</p>
              {shownPreview && <p className="muted">{shownEvents.filter(event => event.extendedProps?.kind === 'fixed').length} {t('khối', 'blocks')}
                {' · '}{shownEvents.filter(event => event.display === 'background').length} {t('dải ngủ mặc định', 'default sleep bands')}</p>}</>}
        </section>
        <section className="panel">
          <div className="panel-heading"><span className="panel-icon lavender"><Icon name="clock" /></span>
            <h2>{t('Xếp lịch', 'Schedule tasks')}</h2></div>
          <form className="form-stack" onSubmit={event => { event.preventDefault(); runPlan() }}>
            <label>{t('Có thể dậy sớm hơn (phút)', 'Can wake earlier (minutes)')}
              <input type="number" min="0" max="60" required value={earlier} onChange={event => setEarlier(+event.target.value)} /></label>
            <label>{t('Có thể ngủ muộn hơn (phút)', 'Can stay up later (minutes)')}
              <input type="number" min="0" max="60" required value={later} onChange={event => setLater(+event.target.value)} /></label>
            <button className="primary" disabled={busy || errors || !draft.deadline_tasks.length}>
              {busy ? t('Đang xử lý…', 'Working…') : t('Chạy xếp lịch', 'Run scheduler')}</button>
          </form>
          {Boolean(shownPreview) && !visiblePlan && <p className="muted">{t('Thời gian rảnh', 'Free time')} · {shownPreview?.free_minutes}′</p>}
          {!draft.deadline_tasks.length && <p className="muted">{t('Thêm ít nhất một việc có hạn chót để chạy xếp lịch.',
            'Add at least one deadline task to run the scheduler.')}</p>}
          {draft.issues.length > 0 && <details><summary>{t('Kiểm tra dữ liệu', 'Input validation')}</summary><Issues issues={draft.issues} t={t} /></details>}
          {!errors && <a className="text-link" href={API + (activePlan ? `/plans/${activePlan.id}/snapshot` : '/draft/snapshot')}>
            {t('Tải snapshot JSON', 'Download JSON snapshot')}</a>}
        </section>
        {activePlan && <section className="panel form-stack">
          <div className="panel-heading"><span className={activePlan.unscheduled.length ? 'panel-icon amber' : 'panel-icon mint'}><Icon name="check" /></span>
            <h2>{t('Kết quả', 'Result')}</h2></div>
          <p className="muted">{activePlan.optimal ? t('Solver đã chứng minh lịch tối ưu.', 'Solver proved optimality.') :
            t('Lịch tốt nhất tìm được trong thời gian chạy.', 'Best schedule found within the time limit.')}</p>
          {activePlan.unscheduled.length ? <>
            <label>{t('Việc chưa xếp', 'Unscheduled task')}<select value={targetId} onChange={event => setTarget(event.target.value)}>
              {activePlan.unscheduled.map(task => <option key={task.id} value={task.id}>{task.name} ({task.minutes}′)</option>)}
            </select></label>
            <button onClick={analyze} disabled={busy}>{t('Phân tích 3 phương án', 'Analyze 3 options')}</button>
          </> : <p>{t('Đã xếp đủ các việc còn giữ.', 'All retained tasks were scheduled.')}</p>}
          {activePlan.applied.length > 0 && <details><summary>{t('Phương án đã áp dụng', 'Applied options')} ({activePlan.applied.length})</summary>
            <ul className="simple-list">{activePlan.applied.map((value, index) => <li key={index}>
              {value.target_task_name} · {optionTitle(value.option_id, t)}{value.duration_min ? ` · ${value.duration_min}′` : ''}</li>)}</ul>
          </details>}
          <button disabled={busy} onClick={() => void perform(async () => {
            await sendOperation(`/plans/${activePlan.id}/history`, { expected_version: activePlan.version })
            setStatus(t('Đã lưu phiên bản vào lịch sử.', 'Version saved to history.'))
          })}>{t('Lưu vào lịch sử', 'Save to history')}</button>
          <button className="primary" disabled={busy} onClick={() => activePlan.schedule_key ?
            setRatingKey(activePlan.schedule_key) : void finalize(false)}>
            {activePlan.schedule_key ? t('Mở đánh giá', 'Open rating') : t('Chốt và đánh giá', 'Finalize and rate')}</button>
          <button disabled={busy} onClick={() => void finalize(true)}>{t('Tải lịch JSON', 'Download schedule JSON')}</button>
        </section>}
      </aside>
    </div>
    {report && activePlan && <section className="panel form-stack">
      <div className="section-head"><h2>{t('Phương án xử lý xung đột', 'Conflict options')}</h2>
        <span className="muted">AI · {report.ai_status}</span></div>
      {report.options.map(option => <ConflictOption key={`${activePlan.id}:${activePlan.version}:${targetId}:${option.id}`}
        option={option} week={activePlan.week_start} lang={lang} t={t} busy={busy} apply={apply} />)}
    </section>}
    {expanded && !edit && !selected && <Modal title={weekLabel(week, lang)} onClose={() => setExpanded(false)} busy={busy} t={t} wide>
      <ErrorBox error={error} t={t} reload={refresh} />
      <Calendar events={shownEvents} week={week} lang={lang} t={t} mode={calendarMode} expanded onEvent={showEvent} onDrop={moveEvent} />
    </Modal>}
    {edit && <TaskEditor edit={edit} draft={draft} change={change} close={() => setEdit(null)} reload={refresh} t={t} />}
    {selected && <Modal title={selected.title} onClose={() => setSelected(null)} t={t}>
      <dl className="details-list">
        <dt>{t('Loại', 'Type')}</dt><dd>{blockType(selected.extendedProps.kind === 'reserve' && !selected.extendedProps.task_id ? 'rest' : selected.extendedProps.kind, t)}</dd>
        <dt>{t('Giờ', 'Time')}</dt><dd>{selected.startStr.slice(0, 16).replace('T', ' ')} → {selected.endStr.slice(0, 16).replace('T', ' ')}</dd>
        {duration != null && <><dt>{t('Thời lượng khối', 'Block duration')}</dt><dd>{duration}′</dd></>}
        {deadline && <><dt>{t('Hạn chót', 'Deadline')}</dt><dd>{deadline.deadline.replace('T', ' ')}</dd>
          <dt>{t('Mức quan trọng', 'Importance')}</dt><dd>{deadline.importance}/3</dd>
          <dt>{t('Bắt buộc', 'Required')}</dt><dd>{deadline.mandatory ? t('Có', 'Yes') : t('Không', 'No')}</dd>
          <dt>{t('Tổng thời lượng', 'Total duration')}</dt><dd>{deadline.remaining_min}′</dd></>}
        {eventTask?.start && <><dt>{t('Thời gian chuẩn bị', 'Preparation time')}</dt><dd>{eventTask.prep_min}′</dd>
          <dt>{t('Thời gian dự trù', 'Travel time')}</dt><dd>{eventTask.after_min}′</dd></>}
      </dl>
    </Modal>}
    {ratingKey && <Modal title={t('Đánh giá lịch vừa chốt', 'Rate this schedule')} onClose={() => setRatingKey(null)} t={t}>
      <RatingForm client={client} ratingKey={ratingKey} t={t} />
    </Modal>}
  </>
}
