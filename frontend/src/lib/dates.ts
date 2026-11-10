// Article-date helpers: relative ages for the first week ("3h ago"),
// absolute dates after ("Jun 12", year appended when it differs from the current one).

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const WEEK = 7 * DAY

/** Format an ISO timestamp as a triage-friendly age relative to `now`.
 *
 * Under 1h -> "38m ago"; under 24h -> "5h ago"; under 7d -> "3d ago"; otherwise an
 * absolute "Jun 12" (plus ", 2025" when the year differs from now's). Ages floor, never
 * go negative (clock skew shows "0m ago"). Unparseable input returns "" so a bad feed
 * date renders nothing rather than garbage.
 */
export function formatAge(iso: string, now: Date = new Date()): string {
  const then = new Date(iso)
  if (isNaN(then.getTime())) {
    return ''
  }
  const elapsed = Math.max(0, now.getTime() - then.getTime())
  if (elapsed < HOUR) {
    return `${Math.floor(elapsed / MINUTE)}m ago`
  }
  if (elapsed < DAY) {
    return `${Math.floor(elapsed / HOUR)}h ago`
  }
  if (elapsed < WEEK) {
    return `${Math.floor(elapsed / DAY)}d ago`
  }
  const monthDay = then.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  return then.getFullYear() === now.getFullYear()
    ? monthDay
    : `${monthDay}, ${then.getFullYear()}`
}

/** The date a card should display: published, else collected (flagged for the tooltip).
 *
 * published_at is 100% populated in practice (RSS + Raindrop both provide it); the
 * created_at fallback is defensive so a future source without dates still shows age.
 */
export function cardDate(card: {
  published_at: string | null
  created_at: string
}): { iso: string; collected: boolean } {
  return card.published_at
    ? { iso: card.published_at, collected: false }
    : { iso: card.created_at, collected: true }
}

/** Full local timestamp for tooltips, prefixed when the collected fallback was used. */
export function dateTooltip(date: { iso: string; collected: boolean }): string {
  const full = new Date(date.iso).toLocaleString()
  return date.collected ? `collected ${full}` : `published ${full}`
}
