import FullCalendar from '@fullcalendar/react'
import interactionPlugin from '@fullcalendar/interaction'
import timeGridPlugin from '@fullcalendar/timegrid'
import vi from '@fullcalendar/core/locales/vi'
import enGb from '@fullcalendar/core/locales/en-gb'
import type { EventApi, EventDropArg, EventInput } from '@fullcalendar/core'
import type { Lang } from './api'
import type { T } from './ui'

const plugins = [timeGridPlugin, interactionPlugin]
const locales = [vi, enGb]
const vnClock = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})

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
  // The API exchanges Vietnam wall-clock times. FullCalendar's UTC coercion
  // preserves those fields independently of the browser's local timezone.
  return <div className="calendar-scroll" role="region" tabIndex={0} aria-label={t('Lịch tuần', 'Weekly calendar')}>
    <FullCalendar key={`${week}:${mode ?? ''}`}
      plugins={plugins} initialView="timeGridWeek" initialDate={week}
      locales={locales} locale={lang === 'vi' ? 'vi' : 'en-gb'} timeZone="Asia/Ho_Chi_Minh"
      now={() => vnClock.format(new Date()).replace(' ', 'T')} nowIndicator={!compact}
      firstDay={1} headerToolbar={false} allDaySlot={false} scrollTime={initialScroll(events, mode)}
      scrollTimeReset={false} height={expanded ? 'calc(100dvh - 8rem)' : compact ? 380 : 670} snapDuration="00:10:00"
      events={events} editable={Boolean(onDrop)} eventDurationEditable={false}
      eventDrop={event => { if (onDrop) onDrop(event); else event.revert() }}
      eventClick={event => onEvent?.(event.event)} eventInteractive={Boolean(onEvent)}
      displayEventEnd dayHeaderFormat={{ weekday: 'short', day: 'numeric' }}
      slotLabelFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
      eventTimeFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
      eventClassNames={event => event.event.extendedProps.kind ? [`${event.event.extendedProps.kind}-band`] : []}
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
}

export function weekLabel(week: string, lang: Lang) {
  const start = new Date(`${week}T00:00:00Z`)
  const end = new Date(start.getTime() + 6 * 86400000)
  const format = new Intl.DateTimeFormat(lang === 'vi' ? 'vi-VN' : 'en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
  })
  return format.formatRange(start, end)
}
