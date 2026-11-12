// Formatting helpers: brief dates, relative times, reading time, source lines, capture labels
// and markdown-to-plain-text for "Copy as plain text".
import type { StorySource } from '../api/types'

const LOCALE = 'en-GB'

/**
 * Parse an ISO timestamp from the service. A timestamp with no zone ("2026-11-12T10:00:00") is UTC,
 * because the service stores UTC without writing the zone; reading it as local time would be off by
 * the viewer's UTC offset. Null for an empty or unparseable value. Every time shown anywhere in the
 * interface goes through this one function.
 */
export function parseTimestamp(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/i.test(iso)
  const date = new Date(hasZone || !iso.includes('T') ? iso : `${iso}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Parse "YYYY-MM-DD" as a local calendar date (not UTC midnight). */
export function parseDay(day: string): Date {
  const [year, month, date] = day.split('-').map(Number)
  return new Date(year, (month || 1) - 1, date || 1)
}

/** "Thursday 12 November" for a brief day; the year is added when it is not the current year. */
export function formatDayTitle(day: string, now: Date = new Date()): string {
  const date = parseDay(day)
  // Built from parts so the result never gains a locale's comma after the weekday.
  const parts = [
    date.toLocaleDateString(LOCALE, { weekday: 'long' }),
    String(date.getDate()),
    date.toLocaleDateString(LOCALE, { month: 'long' }),
  ]
  if (date.getFullYear() !== now.getFullYear()) parts.push(String(date.getFullYear()))
  return parts.join(' ')
}

/** "Thu 12 Nov" for the day switcher. */
export function formatDayShort(day: string): string {
  return parseDay(day).toLocaleDateString(LOCALE, { weekday: 'short', day: 'numeric', month: 'short' })
}

/** "12 Nov 2026" for an ISO timestamp; '' for null or unparseable input. */
export function formatDate(iso: string | null | undefined): string {
  const date = parseTimestamp(iso)
  return date === null ? '' : date.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short', year: 'numeric' })
}

/** A short relative time: "just now", "14 min ago", "5 h ago", "yesterday", "3 days ago", or a date. */
export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  const then = parseTimestamp(iso)
  if (then === null) return ''
  const minutes = Math.round((now.getTime() - then.getTime()) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days} days ago`
  return then.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short' })
}

/** How many words a reader gets through in a minute. */
export const WORDS_PER_MINUTE = 230

/** Minutes to read a text of `words` words at about 230 words a minute (at least 1). */
export function readMinutes(words: number): number {
  return Math.max(1, Math.round(words / WORDS_PER_MINUTE))
}

/**
 * The reading time shown in the interface: "6 min read", or "under a minute" when the text takes
 * less than a minute (never "0 min read"). `minutes` may be fractional; it is rounded to the minute.
 */
export function readingTimeLabel(minutes: number): string {
  const rounded = Math.round(minutes)
  return rounded < 1 || !Number.isFinite(rounded) ? 'under a minute' : `${rounded} min read`
}

/** "Publication · Publication · +3": the first two source names and how many more there are. */
export function sourcesLine(sources: StorySource[], total = sources.length, shown = 2): string {
  const names = Array.from(new Set(sources.map((source) => source.name).filter(Boolean)))
  const head = names.slice(0, shown)
  const rest = Math.max(0, Math.max(total, names.length) - head.length)
  return rest > 0 ? [...head, `+${rest}`].join(' · ') : head.join(' · ')
}

/**
 * "Medtronic · Imaging AI": which watched organisation(s) a watch-list story is about. Names are
 * de-duplicated; at most two are shown and the rest are counted. Returns null when none.
 */
export function watchLabel(watch: { name: string; category?: string | null }[] | null | undefined): string | null {
  if (!Array.isArray(watch)) return null
  const entries = watch.filter((entry) => entry && typeof entry.name === 'string' && entry.name.trim())
  if (!entries.length) return null
  const unique = entries.filter((entry, index) => entries.findIndex((other) => other.name === entry.name) === index)
  const shown = unique.slice(0, 2).map((entry) => (entry.category ? `${entry.name} · ${entry.category}` : entry.name))
  const rest = unique.length - shown.length
  return rest > 0 ? `${shown.join(', ')} +${rest}` : shown.join(', ')
}

const CAPTURE_LABELS: Record<string, string> = {
  slack: 'from Slack',
  raindrop: 'from Raindrop',
  email: 'by email',
  gmail: 'by email',
  newsletter: 'by email',
  dashboard: 'from Spyglass',
  manual: 'from Spyglass',
  capture: 'as a link',
  browser: 'from your browser',
  paste: 'as pasted text',
  file: 'as a file',
}

/** "Sent by you from Slack", or plain "Sent by you" when the route is unknown. */
export function sentByYou(capturedVia: string | null | undefined): string {
  const how = capturedVia ? CAPTURE_LABELS[capturedVia.toLowerCase()] ?? `via ${capturedVia}` : ''
  return how ? `Sent by you ${how}` : 'Sent by you'
}

/** Convert markdown to plain text for pasting into email or social posts. */
export function stripMarkdown(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```\w*\n?/g, ''))
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/(^|[^*])\*(?!\s)(.+?)\*/g, '$1$2')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1 ($2)')
    .replace(/^[ \t]*[-*+][ \t]+/gm, '- ')
    .replace(/^>\s?/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** Hostname of a URL without "www.", or '' when it cannot be parsed. */
export function hostOf(url: string | null | undefined): string {
  if (!url) return ''
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}
