import { useEffect, useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import interactionPlugin from '@fullcalendar/interaction'
import timeGridPlugin from '@fullcalendar/timegrid'
import vi from '@fullcalendar/core/locales/vi'
import enGb from '@fullcalendar/core/locales/en-gb'
import type { EventApi, EventDropArg, EventInput } from '@fullcalendar/core'
import type { Lang } from '../lib/api'
import { dateInWeek } from '../lib/dates'
import type { T } from './ui'

const plugins = [timeGridPlugin, interactionPlugin]
const locales = [vi, enGb]
const compactWidth = '(max-width: 680px)'
const calendarWeekdays = { vi: ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'], en: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] }
const vnClock = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})

export function blockType(kind: string, t: T) {
  if (kind === 'fixed') return t('Việc cố định', 'Fixed task')
  if (kind === 'deadline') return t('Việc có hạn chót', 'Deadline task')
  if (kind === 'prep' || kind === 'after' || kind === 'reserve') return t('Chuẩn bị / di chuyển', 'Preparation / travel')
  return kind === 'sleep' ? t('Giờ ngủ', 'Sleep') : t('Nghỉ ngơi', 'Rest')
}

function clockMinutes(value: string) {
  const time = value.match(/(?:T| )(\d{2}):(\d{2})/)
  return time ? Number(time[1]) * 60 + Number(time[2]) : 360
}

function initialScroll(events: EventInput[], mode?: 'draft' | 'plan' | 'now') {
  const minutes = mode === 'now' ? clockMinutes(vnClock.format(new Date())) - 60 : events.reduce((earliest, event) =>
    event.display !== 'background' && typeof event.start === 'string' ?
      Math.min(earliest, clockMinutes(event.start) - 30) : earliest, 360)
  const start = Math.max(0, minutes)
  return `${String(Math.floor(start / 60)).padStart(2, '0')}:${String(start % 60).padStart(2, '0')}:00`
}

export function Calendar({ events, week, lang, t, compact, mode, expanded, onDrop, onEvent }: {
  events: EventInput[]; week: string; lang: Lang; t: T; compact?: boolean; mode?: 'draft' | 'plan' | 'now'; expanded?: boolean
  onDrop?: (event: EventDropArg) => void; onEvent?: (event: EventApi) => void
}) {
  return <CalendarView key={`${week}:${mode ?? ''}`} {...{events, week, lang, t, compact, mode, expanded, onDrop, onEvent}} />
}

function CalendarView({ events, week, lang, t, compact, mode, expanded, onDrop, onEvent }: Parameters<typeof Calendar>[0]) {
  const [narrow, setNarrow] = useState(() => window.matchMedia(compactWidth).matches)
  const [preferred, setPreferred] = useState<'day' | 'week' | null>(null)
  const dates = Array.from({ length: 7 }, (_, day) => dateInWeek(week, day))
  const today = vnClock.format(new Date()).slice(0, 10)
  const [day, setDay] = useState(() => mode === 'now' && dates.includes(today) ? today : week)
  const view = preferred ?? (narrow ? 'day' : 'week')
  const date = view === 'day' ? day : week
  const dateFormat = new Intl.DateTimeFormat(lang === 'vi' ? 'vi-VN' : 'en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC',
  })
  const headerDate = new Intl.DateTimeFormat('en-GB', {
    day: '2-digit', month: '2-digit', timeZone: 'UTC',
  })
  useEffect(() => {
    const media = window.matchMedia(compactWidth)
    const change = (event: MediaQueryListEvent) => setNarrow(event.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  const visibleEvents = view === 'week' ? events : events.filter(event => {
    if (typeof event.start !== 'string') return false
    return event.start.slice(0, 10) <= day && (typeof event.end !== 'string' || event.end.slice(0, 10) >= day)
  })
  // The API exchanges Vietnam wall-clock times. FullCalendar's UTC coercion
  // preserves those fields independently of the browser's local timezone.
  return <div className="calendar-widget">
    <div className="calendar-toolbar">
      <div className="calendar-views" role="group" aria-label={t('Chế độ xem lịch', 'Calendar view')}>
        <button type="button" aria-pressed={view === 'week'} onClick={() => setPreferred('week')}>{t('Cả tuần', 'Week')}</button>
        <button type="button" aria-pressed={view === 'day'} onClick={() => setPreferred('day')}>{t('Một ngày', 'Day')}</button>
      </div>
      {view === 'day' && <div className="day-picker" role="group" aria-label={t('Chọn ngày', 'Choose a day')}>
        {dates.map((value, index) => <button key={value} type="button" aria-pressed={value === day}
          aria-label={dateFormat.format(new Date(value))} onClick={() => setDay(value)}>
          <span>{calendarWeekdays[lang][index]}</span><strong>{Number(value.slice(-2))}</strong>
        </button>)}
      </div>}
    </div>
    <div className={view === 'day' ? 'calendar-scroll calendar-day' : 'calendar-scroll'} role="region" tabIndex={0}
      aria-label={view === 'day' ? t('Lịch từng ngày', 'Daily calendar') : t('Lịch tuần', 'Weekly calendar')}>
    <FullCalendar key={`${view}:${date}`}
      plugins={plugins} initialView={view === 'day' ? 'timeGridDay' : 'timeGridWeek'} initialDate={date}
      locales={locales} locale={lang === 'vi' ? 'vi' : 'en-gb'} timeZone="Asia/Ho_Chi_Minh"
      now={() => vnClock.format(new Date()).replace(' ', 'T')} nowIndicator={!compact}
      firstDay={1} headerToolbar={false} allDaySlot={false} scrollTime={initialScroll(visibleEvents, mode === 'now' && date !== today && view === 'day' ? undefined : mode)}
      scrollTimeReset={false} height={expanded ? 'calc(100dvh - 12rem)' : compact ? 380 : 650} snapDuration="00:10:00"
      eventLongPressDelay={250} eventMinHeight={8}
      events={onDrop ? events : events.map(event => event.editable ? { ...event, editable: false } : event)}
      editable={Boolean(onDrop)} eventDurationEditable={false}
      eventDrop={event => { if (onDrop) onDrop(event); else event.revert() }}
      eventClick={event => onEvent?.(event.event)} eventInteractive={Boolean(onEvent)}
      displayEventEnd dayHeaderContent={({ date }) => {
        const label = dateFormat.format(date)
        return <span className="calendar-day-heading" title={label}>
          <span className="sr-only">{label}</span>
          <strong aria-hidden="true">{calendarWeekdays[lang][(date.getUTCDay() + 6) % 7]}</strong>
          <span aria-hidden="true">{headerDate.format(date)}</span>
        </span>
      }}
      slotLabelFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
      eventTimeFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
      eventClassNames={({ event }) => {
        const kind = event.extendedProps.kind
        const minutes = event.start && event.end ? (event.end.getTime() - event.start.getTime()) / 60000 : 60
        return [...(kind ? [`${kind}-band`] : []), ...(minutes <= 45 ? ['compact-event'] : []),
          ...(minutes < 25 ? ['micro-event'] : [])]
      }}
      eventDidMount={({ el, event, timeText }) => {
        if (event.title) el.title = [event.title, timeText].filter(Boolean).join(' · ')
      }}
      eventContent={event => {
        const kind = event.event.extendedProps.kind
        const prefix = kind === 'prep' ? t('Chuẩn bị', 'Prep') : kind === 'after' ? t('Di chuyển', 'Travel') : ''
        return <div className="event-label">
          {event.timeText && <small>{event.timeText}</small>}
          <strong>{prefix && `${prefix} · `}{event.event.title}</strong>
        </div>
      }}
    />
    </div>
  </div>
}
