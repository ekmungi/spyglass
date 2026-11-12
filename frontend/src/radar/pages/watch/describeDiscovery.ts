// Plain-language outcome of a discovery search.
import type { DiscoverResult } from './api'

/** Words for the outcome of a search: how many names were proposed, and what was left out. */
export function describeDiscovery(result: DiscoverResult): string {
  const found = result.suggested.length
  const known = result.already_known ?? 0
  const head =
    found === 0
      ? 'No new names turned up.'
      : `${found} ${found === 1 ? 'name' : 'names'} added to Suggested.`
  return known > 0 ? `${head} ${known} ${known === 1 ? 'was' : 'were'} already on your list.` : head
}
