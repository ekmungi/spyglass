// Pure helpers for the "Follow more like this" flow: which suggestion is ticked at first, how a
// suggestion is keyed, and the sentence that closes the flow.
import type { TrackKind, TrackSuggestion } from '../api/types'

/** The word shown beside a suggestion for what kind of thing it is. */
export const KIND_LABELS: Record<TrackKind, string> = {
  topic: 'Topic',
  organisation: 'Organisation',
  person: 'Person',
  product: 'Product',
}

/** A stable identity for a suggestion within one reply. */
export function suggestionKey(suggestion: TrackSuggestion): string {
  return `${suggestion.kind}:${suggestion.query}`
}

/** Number of words in a search query, ignoring quote marks. */
function wordCount(query: string): number {
  return query.replace(/["']/g, ' ').split(/\s+/).filter(Boolean).length
}

/**
 * The single most specific suggestion that is not followed yet: the longest query (a narrower
 * search), then a named thing over a general topic, then the first listed. Null when none is left.
 */
export function mostSpecific(suggestions: readonly TrackSuggestion[]): TrackSuggestion | null {
  const open = suggestions.filter((suggestion) => !suggestion.already_followed)
  let best: TrackSuggestion | null = null
  for (const candidate of open) {
    if (best === null) {
      best = candidate
      continue
    }
    const gain = wordCount(candidate.query) - wordCount(best.query)
    const namedGain = Number(candidate.kind !== 'topic') - Number(best.kind !== 'topic')
    if (gain > 0 || (gain === 0 && namedGain > 0)) best = candidate
  }
  return best
}

/**
 * "Following 2 topics · 7 new items found; they will be judged in the next collection" (the second
 * part only when something was found: new items are not assessed until the next collection runs).
 */
export function followSummary(followed: number, found: number): string {
  const head = `Following ${followed} ${followed === 1 ? 'topic' : 'topics'}`
  if (found <= 0) return head
  return `${head} · ${found} new ${found === 1 ? 'item' : 'items'} found; ${found === 1 ? 'it' : 'they'} will be judged in the next collection`
}
