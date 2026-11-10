// Tests for relevance helpers: filter logic and dot color mapping.
import { describe, expect, it } from 'vitest'
import {
  displayedRelevance,
  passesRelevanceFilter,
  relevanceColor,
  RELEVANCE_FILTERS,
  RELEVANCE_LEVELS,
} from './relevance'

describe('passesRelevanceFilter', () => {
  it('"all" shows everything including null and out', () => {
    expect(passesRelevanceFilter('high', 'all')).toBe(true)
    expect(passesRelevanceFilter('medium', 'all')).toBe(true)
    expect(passesRelevanceFilter('low', 'all')).toBe(true)
    expect(passesRelevanceFilter('out', 'all')).toBe(true)
    expect(passesRelevanceFilter(null, 'all')).toBe(true)
  })

  it('"unjudged" shows only null effective_relevance', () => {
    expect(passesRelevanceFilter(null, 'unjudged')).toBe(true)
    expect(passesRelevanceFilter('high', 'unjudged')).toBe(false)
    expect(passesRelevanceFilter('medium', 'unjudged')).toBe(false)
    expect(passesRelevanceFilter('low', 'unjudged')).toBe(false)
    expect(passesRelevanceFilter('out', 'unjudged')).toBe(false)
  })

  it('"medium" level shows high and medium but hides low, out, and null', () => {
    expect(passesRelevanceFilter('high', 'medium')).toBe(true)
    expect(passesRelevanceFilter('medium', 'medium')).toBe(true)
    expect(passesRelevanceFilter('low', 'medium')).toBe(false)
    expect(passesRelevanceFilter('out', 'medium')).toBe(false)
    expect(passesRelevanceFilter(null, 'medium')).toBe(false)
  })

  it('"high" level shows only high', () => {
    expect(passesRelevanceFilter('high', 'high')).toBe(true)
    expect(passesRelevanceFilter('medium', 'high')).toBe(false)
    expect(passesRelevanceFilter('low', 'high')).toBe(false)
    expect(passesRelevanceFilter('out', 'high')).toBe(false)
    expect(passesRelevanceFilter(null, 'high')).toBe(false)
  })

  it('"low" level shows high, medium, and low but hides out and null', () => {
    expect(passesRelevanceFilter('high', 'low')).toBe(true)
    expect(passesRelevanceFilter('medium', 'low')).toBe(true)
    expect(passesRelevanceFilter('low', 'low')).toBe(true)
    expect(passesRelevanceFilter('out', 'low')).toBe(false)
    expect(passesRelevanceFilter(null, 'low')).toBe(false)
  })

  it('"out" shows only filtered-out items, for reviewing what the model rejected', () => {
    expect(passesRelevanceFilter('out', 'out')).toBe(true)
    expect(passesRelevanceFilter('high', 'out')).toBe(false)
    expect(passesRelevanceFilter('medium', 'out')).toBe(false)
    expect(passesRelevanceFilter('low', 'out')).toBe(false)
    expect(passesRelevanceFilter(null, 'out')).toBe(false)
  })
})

describe('displayedRelevance', () => {
  it('uses effective_relevance when the service provides it', () => {
    expect(displayedRelevance({ effective_relevance: 'high', relevance: 'low' })).toBe('high')
  })

  it('keeps null (unjudged) from a modern backend, not falling back to the bucket', () => {
    expect(displayedRelevance({ effective_relevance: null, relevance: 'high' })).toBeNull()
  })

  it('falls back to the stored bucket when the field is ABSENT (older backend)', () => {
    expect(displayedRelevance({ relevance: 'medium' })).toBe('medium')
  })

  it('is null when neither value is available', () => {
    expect(displayedRelevance({ relevance: null })).toBeNull()
  })
})

describe('relevanceColor', () => {
  it('maps each level to a theme color variable', () => {
    expect(relevanceColor('high')).toBe('var(--color-ok)')
    expect(relevanceColor('medium')).toBe('var(--color-accent2)')
    expect(relevanceColor('low')).toBe('var(--color-muted)')
    expect(relevanceColor('out')).toBe('var(--color-out)')
  })

  it('maps unjudged to the border color', () => {
    expect(relevanceColor(null)).toBe('var(--color-border)')
  })
})

describe('RELEVANCE_LEVELS', () => {
  it('lists the four levels from high to out for menus', () => {
    expect(RELEVANCE_LEVELS.map((l) => l.value)).toEqual(['high', 'medium', 'low', 'out'])
  })
})

describe('RELEVANCE_FILTERS', () => {
  it('lists all, unjudged, high, medium, low, out in that order', () => {
    expect(RELEVANCE_FILTERS.map((f) => f.value)).toEqual([
      'all',
      'unjudged',
      'high',
      'medium',
      'low',
      'out',
    ])
  })

  it('labels the level filters as floors so "& up" semantics are visible', () => {
    expect(RELEVANCE_FILTERS.map((f) => f.label)).toEqual([
      'All',
      'Unjudged',
      'High',
      'Medium & up',
      'Low & up',
      'Out only',
    ])
  })
})
