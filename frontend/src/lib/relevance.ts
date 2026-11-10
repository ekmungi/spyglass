// Relevance helpers: filter model, level metadata, dot colors.
import type { Relevance } from './types'

// Rank order used for filter comparison; higher = more relevant.
const ORDER: Record<Relevance, number> = { high: 3, medium: 2, low: 1, out: 0 }

// The four levels in menu order, with the short labels from the mockup.
export const RELEVANCE_LEVELS: { value: Relevance; label: string }[] = [
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Med' },
  { value: 'low', label: 'Low' },
  { value: 'out', label: 'Out' },
]

/** The possible values for the relevance hide-filter.
 * 'all' = show everything; 'unjudged' = only null-effective cards;
 * 'out' = only filtered-out cards (review what the model rejected);
 * a level = only cards whose effective_relevance ranks at or above that level. */
export type RelevanceFilter = 'all' | 'unjudged' | 'high' | 'medium' | 'low' | 'out'

/** Ordered filter options for the filter bar dropdown.
 * Level labels spell out the floor semantics ("& up") — a level filter keeps everything AT OR
 * ABOVE that rank, so "Low & up" showing medium items is expected, not stale.
 * "Out only" is an exact view like Unjudged, not a floor (a floor at 'out' would equal All). */
export const RELEVANCE_FILTERS: { value: RelevanceFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'unjudged', label: 'Unjudged' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium & up' },
  { value: 'low', label: 'Low & up' },
  { value: 'out', label: 'Out only' },
]

/** The relevance level to display and filter a card on.
 *
 * Prefers the service's blended `effective_relevance`; falls back to the stored `relevance`
 * bucket ONLY when the field is entirely absent -- i.e. an older backend that predates it, so a
 * version mismatch never blanks the list. A modern backend's explicit `null` (unjudged) is kept
 * as-is (not overridden by the bucket). */
export function displayedRelevance(card: {
  effective_relevance?: Relevance | null
  relevance: Relevance | null
}): Relevance | null {
  return card.effective_relevance === undefined ? card.relevance ?? null : card.effective_relevance
}

/** Returns true when a card with the given effective_relevance should be shown
 * under the active filter.
 *
 * Rules:
 *   'all'      → always true (show everything, including null and 'out').
 *   'unjudged' → true only when effective is null.
 *   'out'      → true only when effective is 'out' (review the rejected pile).
 *   level      → true when effective is a judged level at or above that rank.
 *                null (unjudged) and 'out' are HIDDEN under any level filter.
 */
export function passesRelevanceFilter(effective: Relevance | null, filter: RelevanceFilter): boolean {
  if (filter === 'all') {
    return true
  }
  if (filter === 'unjudged') {
    return effective === null
  }
  if (filter === 'out') {
    return effective === 'out'
  }
  // level filter: null and 'out' are hidden
  if (effective === null || effective === 'out') {
    return false
  }
  return ORDER[effective] >= ORDER[filter]
}

/** Theme color variable for a relevance dot (border color when unjudged). */
export function relevanceColor(relevance: Relevance | null): string {
  switch (relevance) {
    case 'high':
      return 'var(--color-ok)'
    case 'medium':
      return 'var(--color-accent2)'
    case 'low':
      return 'var(--color-muted)'
    case 'out':
      return 'var(--color-out)'
    default:
      return 'var(--color-border)'
  }
}
