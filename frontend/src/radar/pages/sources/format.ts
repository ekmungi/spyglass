// Date and time wording shared by the secondary pages: short, local, and never a raw ISO string.
import { parseTimestamp } from '../../lib/format'

const MONTH_DAY: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' }
const MONTH_DAY_YEAR: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' }
const CLOCK: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' }

/** Parse an ISO string (zone-less timestamps are UTC); null when it is empty or not a date. Same rule as everywhere else. */
export const parseWhen = parseTimestamp

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/** "12 Nov" (or "12 Nov 2025" when the year differs from `now`); empty string for no date. */
export function formatDay(iso: string | null | undefined, now: Date = new Date()): string {
  const date = parseWhen(iso)
  if (!date) return ''
  return date.toLocaleDateString(undefined, date.getFullYear() === now.getFullYear() ? MONTH_DAY : MONTH_DAY_YEAR)
}

/** "today at 14:05", "yesterday at 14:05", or "12 Nov at 14:05"; empty string for no date. */
export function formatWhen(iso: string | null | undefined, now: Date = new Date()): string {
  const date = parseWhen(iso)
  if (!date) return ''
  const clock = date.toLocaleTimeString(undefined, CLOCK)
  if (sameDay(date, now)) return `today at ${clock}`
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (sameDay(date, yesterday)) return `yesterday at ${clock}`
  return `${formatDay(iso, now)} at ${clock}`
}

/** Like formatWhen for a moment that may lie ahead: "today at 06:30", "tomorrow at 06:30", "13 Nov at 06:30". */
export function formatUpcoming(iso: string | null | undefined, now: Date = new Date()): string {
  const date = parseWhen(iso)
  if (!date) return ''
  const tomorrow = new Date(now)
  tomorrow.setDate(now.getDate() + 1)
  if (sameDay(date, tomorrow)) return `tomorrow at ${date.toLocaleTimeString(undefined, CLOCK)}`
  return formatWhen(iso, now)
}

/** True when `iso` falls within the last `days` days before `now`. */
export function isWithinDays(iso: string | null | undefined, days: number, now: Date = new Date()): boolean {
  const date = parseWhen(iso)
  if (!date) return false
  const age = now.getTime() - date.getTime()
  // A timestamp a little ahead of this machine's clock still counts as recent.
  return age <= days * 24 * 60 * 60 * 1000
}
