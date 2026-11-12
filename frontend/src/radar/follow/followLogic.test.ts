// Tests for the pure helpers of the follow flow: the first tick, keys and the closing sentence.
import { describe, expect, it } from 'vitest'
import type { TrackSuggestion } from '../api/types'
import { followSummary, mostSpecific, suggestionKey } from './followLogic'

function line(over: Partial<TrackSuggestion>): TrackSuggestion {
  return { label: 'x', query: 'x', kind: 'topic', section: 'health', section_label: 'Health', why: '', already_followed: false, ...over }
}

describe('mostSpecific', () => {
  it('picks the longest query', () => {
    const picked = mostSpecific([line({ query: 'surgery' }), line({ query: 'endoscopic bladder tumor resection' }), line({ query: 'robot surgery' })])
    expect(picked?.query).toBe('endoscopic bladder tumor resection')
  })

  it('prefers a named thing over a topic when the length ties, and the first otherwise', () => {
    expect(mostSpecific([line({ query: 'surgical robots' }), line({ query: '"Intuitive Surgical"', kind: 'organisation' })])?.kind).toBe('organisation')
    expect(mostSpecific([line({ label: 'a', query: 'one two' }), line({ label: 'b', query: 'three four' })])?.label).toBe('a')
  })

  it('skips what is already followed and returns null when nothing is left', () => {
    expect(mostSpecific([line({ query: 'a b c', already_followed: true }), line({ query: 'd' })])?.query).toBe('d')
    expect(mostSpecific([line({ already_followed: true })])).toBeNull()
    expect(mostSpecific([])).toBeNull()
  })
})

describe('followSummary and suggestionKey', () => {
  it('words the result and mentions judging only when items were found', () => {
    expect(followSummary(2, 7)).toBe('Following 2 topics · 7 new items found; they will be judged in the next collection')
    expect(followSummary(1, 1)).toBe('Following 1 topic · 1 new item found; it will be judged in the next collection')
    expect(followSummary(1, 0)).toBe('Following 1 topic')
  })

  it('keys a suggestion by kind and query', () => {
    expect(suggestionKey(line({ kind: 'person', query: '"Jane Roe"' }))).toBe('person:"Jane Roe"')
  })
})
