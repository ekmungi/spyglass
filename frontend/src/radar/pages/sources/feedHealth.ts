// Feed health in words: which feeds fail, the alert for the Feeds tab, and the one line of counts that
// stands in for the feeds that work.
import type { FeedRow } from './api'
import { feedStatus } from './describe'

/** Whether a feed is failing: switched on, and its last fetch went wrong. A switched-off feed is not. */
export function isFailing(feed: FeedRow): boolean {
  return feedStatus(feed).tone === 'problem'
}

/** The two lists of the Feeds group: the folded working feeds, and the others that are always listed. */
export type FeedGroup = 'working' | 'others'

/** The list a feed belongs to by its state now. */
export function feedGroup(feed: FeedRow): FeedGroup {
  return feedStatus(feed).tone === 'ok' ? 'working' : 'others'
}

/** The feeds that work, and the feeds in any other state (failing, switched off, not fetched yet), each in the given order. */
export function splitFeeds(feeds: readonly FeedRow[]): { working: FeedRow[]; others: FeedRow[] } {
  return placeFeeds(feeds, new Map())
}

/**
 * The feeds as the page lists them: each in the list of its state, except a feed in `kept`, which stays
 * in the list it was in when the reader changed it, so it does not move or vanish under the cursor.
 */
export function placeFeeds(feeds: readonly FeedRow[], kept: ReadonlyMap<number, FeedGroup>): { working: FeedRow[]; others: FeedRow[] } {
  const working: FeedRow[] = []
  const others: FeedRow[] = []
  for (const feed of feeds) ((kept.get(feed.id) ?? feedGroup(feed)) === 'working' ? working : others).push(feed)
  return { working, others }
}

/** The alert text for the Feeds tab ("1 feed is failing"), or undefined when no feed fails. */
export function failingAlert(feeds: readonly FeedRow[]): string | undefined {
  const count = feeds.filter(isFailing).length
  if (count === 0) return undefined
  return count === 1 ? '1 feed is failing' : `${count} feeds are failing`
}

/** "3 switched off, 1 failing": how many of the given feeds are in each state that is not working. */
export function otherFeedsSummary(others: readonly FeedRow[]): string {
  const off = others.filter((feed) => !feed.enabled).length
  const failing = others.filter(isFailing).length
  const waiting = others.length - off - failing
  return [off && `${off} switched off`, waiting && `${waiting} not fetched yet`, failing && `${failing} failing`].filter(Boolean).join(', ')
}
