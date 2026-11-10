// Tests for filter facet derivation and matching.
import { describe, expect, it } from 'vitest'
import { makeCard } from '../test/fixtures'
import { deriveFacets, EMPTY_FILTER, matchesFilter } from './filters'

const base = makeCard({
  tags: ['agentic'], category: 'AI', group: 'Agents', source_tags: ['papers'],
})

describe('deriveFacets', () => {
  it('collects distinct sorted facet values; sources are publications, not collectors', () => {
    const cards = [
      base,
      {
        ...base,
        id: 2,
        source: 'raindrop',
        url: 'https://forbes.com/x',
        category: 'Health',
        tags: [],
      },
    ]
    const facets = deriveFacets(cards)
    // base url is https://example.test/1 -> brand label "Example".
    expect(facets.source).toEqual(['Example', 'Forbes'])
    expect(facets.category).toEqual(['AI', 'Health'])
    expect(facets.tag).toEqual(['agentic', 'papers'])
  })

  it('omits null facet values', () => {
    const facets = deriveFacets([{ ...base, category: null, group: null }])
    expect(facets.category).toEqual([])
    expect(facets.group).toEqual([])
  })
})

describe('matchesFilter', () => {
  it('passes everything when the filter is empty', () => {
    expect(matchesFilter(base, EMPTY_FILTER)).toBe(true)
  })

  it('filters by source (publication), category, group, and tag', () => {
    expect(matchesFilter(base, { ...EMPTY_FILTER, source: 'Forbes' })).toBe(false)
    expect(matchesFilter(base, { ...EMPTY_FILTER, source: 'Example' })).toBe(true)
    expect(matchesFilter(base, { ...EMPTY_FILTER, category: 'AI' })).toBe(true)
    expect(matchesFilter(base, { ...EMPTY_FILTER, group: 'Other' })).toBe(false)
    expect(matchesFilter(base, { ...EMPTY_FILTER, tag: 'papers' })).toBe(true)
  })
})
