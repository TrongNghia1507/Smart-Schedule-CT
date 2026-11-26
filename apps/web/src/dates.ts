import type { Lang } from './api'

const vietnamDate = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh', dateStyle: 'short' })

export function vietnamDay(now: Date) {
  return vietnamDate.format(now)
}

export function currentMonday() {
  const today = vietnamDay(new Date())
  return dateInWeek(today, -((new Date(today).getUTCDay() + 6) % 7))
}

export function dateInWeek(week: string, day: number) {
  const start = Date.parse(`${week}T00:00:00Z`)
  return new Date(start + day * 86400000).toISOString().slice(0, 10)
}

export function weekLabel(week: string, lang: Lang) {
  const format = new Intl.DateTimeFormat(lang === 'vi' ? 'vi-VN' : 'en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
  })
  return format.formatRange(new Date(week), new Date(dateInWeek(week, 6)))
}
