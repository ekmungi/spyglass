// Plain-language wording for source health: raw exception text and status codes become one
// sentence a reader can act on. Failures are never shown as bare codes.
import type { CollectorRow, FeedRow } from './api'

const RULES: ReadonlyArray<readonly [RegExp, string]> = [
  [/\b(401|403)\b|forbidden|unauthori[sz]ed/i, 'The site refused access.'],
  [/\b404\b|not found/i, 'The address no longer exists; the site answered "not found".'],
  [/\b410\b/, 'The site says this feed was removed.'],
  [/\b429\b|too many requests|rate.?limit/i, 'The site asked Spyglass to slow down.'],
  [/\b5\d\d\b|server error|bad gateway|service unavailable/i, 'The site had a problem on its side.'],
  [/timed? ?out|timeout/i, 'The site did not answer in time.'],
  [/ssl|certificate/i, "The site's security certificate could not be verified."],
  [/getaddrinfo|name or service|dns|resolve|connection (refused|reset|error|aborted)|unreachable|network/i, 'Spyglass could not reach the site.'],
  [/parse|xml|not well-formed|no feed|not a feed|invalid|malformed/i, 'The address did not return a readable feed.'],
]

/** A message that already reads as a sentence (several words, capitalised, no exception names). */
function readsAsSentence(text: string): boolean {
  const looksLikeLogLine = /^[A-Za-z_.]+:\s/.test(text) || /\w=\w/.test(text) || /(Error|Exception)\b/.test(text)
  return /^[A-Z][^\n]{15,}[.!]$/.test(text) && !looksLikeLogLine && text.split(/\s+/).length >= 4
}

/** Drop a leading "SomeError: " exception name from a log line. */
function stripExceptionName(text: string): string {
  return text.replace(/^[A-Za-z_.]*(Error|Exception|Warning)\s*:\s*/, '').trim()
}

/** One sentence for why a fetch failed; `null` means no reason was recorded. */
export function describeFailure(raw: string | null | undefined): string {
  const text = (raw ?? '').trim()
  if (!text) return 'The last attempt failed, and no reason was recorded.'
  if (readsAsSentence(text)) return text
  for (const [pattern, sentence] of RULES) {
    if (pattern.test(text)) return sentence
  }
  const cleaned = stripExceptionName(text).slice(0, 140)
  return `The last attempt failed: ${cleaned}${/[.!?]$/.test(cleaned) ? '' : '.'}`
}

export interface StatusLine {
  /** The words shown next to the source. */
  text: string
  tone: 'ok' | 'problem' | 'quiet'
}

/** Status words for a feed row: working, failing with the reason, or not fetched yet. */
export function feedStatus(feed: FeedRow): StatusLine {
  if (!feed.enabled) return { text: 'Switched off', tone: 'quiet' }
  if (feed.status === 'error') return { text: describeFailure(feed.error), tone: 'problem' }
  if (feed.status === 'never') return { text: 'Not fetched yet', tone: 'quiet' }
  return { text: 'Working', tone: 'ok' }
}

/** Whether a collector has never been set up (as opposed to failing). */
export function isNotConfigured(row: CollectorRow | undefined): boolean {
  return !row || row.status === 'skipped' || row.status === 'off' || row.enabled === false
}

/** Status words for a collector row. */
export function collectorStatus(row: CollectorRow): StatusLine {
  if (row.status === 'error') return { text: describeFailure(row.detail), tone: 'problem' }
  if (isNotConfigured(row)) return { text: 'Not configured', tone: 'quiet' }
  if (row.status === 'never') return { text: 'Has not run yet', tone: 'quiet' }
  return { text: 'Working', tone: 'ok' }
}

/** "3 new items" / "Nothing new" for a collector's last run; empty when unknown. */
export function newItemsText(count: number | null): string {
  if (count === null) return ''
  if (count === 0) return 'nothing new'
  return `${count} new ${count === 1 ? 'item' : 'items'}`
}
