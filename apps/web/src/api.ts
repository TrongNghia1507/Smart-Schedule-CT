import type { EventInput } from '@fullcalendar/core'

export type Lang = 'vi' | 'en'
export type User = { id: number; username: string; full_name: string; role: 'user' | 'admin' }
export type Session = { user: User; csrf: string }
export type Issue = { code?: string; severity?: 'Error' | 'Warning' | 'Info'; field: string; task_id?: string; message: string }
export type Task = Record<string, string>
export type Draft = {
  revision: number
  settings: { week_start: string; sleep: { start: string; end: string } }
  fixed_tasks: Task[]; deadline_tasks: Task[]; colors: Record<string, string>
  issues: Issue[]; can_undo: boolean; notes: string[]
}
export type Preview = { revision: number; week_start: string; events: EventInput[]; free_minutes: number; now: string; issues: Issue[] }
export type Unplaced = { name: string; minutes: number }
export type Option = {
  id: number; available: boolean; reason: string | null; descriptions: string[]; warnings: string[]
  minimum: number | null; maximum: number | null; explanation: string | null; unplaced: Unplaced[]; events: EventInput[]
}
export type Plan = {
  id: string; draft_revision: number; week_start: string; version: number; optimal: boolean
  earlier: number; later: number; schedule_key: string | null; status: string; events: EventInput[]
  unscheduled: (Unplaced & { id: string })[]
  deadline_details: Record<string, { deadline: string; importance: number; mandatory: boolean; remaining_min: number }>
  reports: Record<string, { ai_status: string; options: Option[] }>
  applied: { option_id: number; target_task_name: string; duration_min: number | null }[]
}
export type HistorySummary = {
  id: string; week_start: string; version: number | null; title: string | null
  description: string | null; saved_at: string; complete: boolean
}
export type HistoryDetail = {
  record: HistorySummary & { context: { tasks: { id: string; name: string }[] }; result: { unscheduled?: Record<string, number> } }
  events: EventInput[]
  entries: { name: string; kind: string; start: string; end: string }[]
}

export const API = '/api/v1'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public issues: Issue[]) {
    super(message)
  }
}

export function createClient(csrf?: string, onExpired?: () => void) {
  async function request(path: string, options: { method?: string; data?: unknown; body?: File } = {}) {
    const { method = 'GET', data, body } = options
    const headers = new Headers()
    headers.set('Accept-Language', new URLSearchParams(location.search).get('lang') ?? document.documentElement.lang)
    if (data !== undefined) headers.set('Content-Type', 'application/json')
    if (body) headers.set('Content-Type', 'application/octet-stream')
    if (csrf && method !== 'GET') headers.set('X-CSRF-Token', csrf)
    const reply = await fetch(API + path, {
      method, headers, body: body ?? (data === undefined ? undefined : JSON.stringify(data)),
      credentials: 'same-origin',
    })
    if (!reply.ok) {
      const result = await reply.json().catch(() => null)
      if (reply.status === 401 && result?.code === 'AUTH_REQUIRED') onExpired?.()
      throw new ApiError(reply.status, result?.code ?? 'REQUEST_FAILED', result?.message ?? `HTTP ${reply.status}`, result?.issues ?? [])
    }
    return reply
  }
  return {
    async get<T>(path: string): Promise<T> {
      return (await request(path)).json()
    },
    async send<T = void>(path: string, data?: unknown, method = 'POST'): Promise<T> {
      const reply = await request(path, { method, data })
      return reply.status === 204 ? (undefined as T) : reply.json()
    },
    async upload<T>(path: string, body: File): Promise<T> {
      return (await request(path, { method: 'POST', body })).json()
    },
    async download(path: string, data: unknown) {
      const response = await request(path, { method: 'POST', data })
      const url = URL.createObjectURL(await response.blob())
      const a = document.createElement('a')
      a.href = url
      a.download = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] ?? 'schedule.json'
      a.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    },
  }
}

export type Client = ReturnType<typeof createClient>
export const anonymous = createClient()
