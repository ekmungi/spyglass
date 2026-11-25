// signalRows: which collectors the "Searches and signals" group lists, so the page can tell whether
// that group has anything to show before it offers the tab.
import type { CollectorRow } from './api'

/** Collectors shown elsewhere on the page: the feeds group covers rss, "From you" the mail and chat ones, FDA has its own group. */
const SHOWN_ELSEWHERE = new Set(['rss', 'slack', 'raindrop', 'gmail', 'newsletter', 'capture', 'fda'])

/** The collectors the "Searches and signals" group lists: every one that no other group already covers. */
export function signalRows(collectors: readonly CollectorRow[]): CollectorRow[] {
  return collectors.filter((row) => !SHOWN_ELSEWHERE.has(row.key))
}
