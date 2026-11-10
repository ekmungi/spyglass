// Filtering helpers: derive available facets from cards and apply a filter state.
import { originLabel } from './source'
import type { CardData } from './types'

export interface FilterState {
  source: string
  category: string
  group: string
  tag: string
}

export const EMPTY_FILTER: FilterState = { source: 'all', category: 'all', group: 'all', tag: 'all' }

/** Distinct sorted values for a facet across the cards (for the filter dropdowns). */
export interface Facets {
  source: string[]
  category: string[]
  group: string[]
  tag: string[]
}

/** Compute the available facet values. Tags merge Claude tags and source tags.
 * The source facet lists actual publications (origin labels), not collectors. */
export function deriveFacets(cards: CardData[]): Facets {
  const set = (values: (string | null | undefined)[]) =>
    [...new Set(values.filter((v): v is string => !!v))].sort()
  return {
    source: set(cards.map((c) => originLabel(c))),
    category: set(cards.map((c) => c.category)),
    group: set(cards.map((c) => c.group)),
    tag: set(cards.flatMap((c) => [...c.tags, ...c.source_tags])),
  }
}

/** True if a card passes the active filter state. */
export function matchesFilter(card: CardData, filter: FilterState): boolean {
  if (filter.source !== 'all' && originLabel(card) !== filter.source) return false
  if (filter.category !== 'all' && card.category !== filter.category) return false
  if (filter.group !== 'all' && card.group !== filter.group) return false
  if (filter.tag !== 'all' && ![...card.tags, ...card.source_tags].includes(filter.tag)) {
    return false
  }
  return true
}
