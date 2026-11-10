// Tests for the card:<id> link parser used by the Brief tab.
import { describe, expect, it } from 'vitest'
import { parseCardIds, parseCardLinks } from './briefLinks'

describe('parseCardIds', () => {
  it('extracts ids from card: markdown links in order', () => {
    const markdown = 'See [A](card:12) then [B](card:7).'
    expect(parseCardIds(markdown)).toEqual([12, 7])
  })

  it('deduplicates repeated references', () => {
    const markdown = '[A](card:3) again [A revisited](card:3) and [B](card:4)'
    expect(parseCardIds(markdown)).toEqual([3, 4])
  })

  it('ignores ordinary links and returns [] when no card links exist', () => {
    expect(parseCardIds('see [docs](https://example.com) and plain text')).toEqual([])
  })
})

describe('parseCardLinks', () => {
  it('extracts {id, title} pairs in order of appearance', () => {
    const markdown = 'See [Alpha](card:12) then [Beta](card:7).'
    expect(parseCardLinks(markdown)).toEqual([
      { id: 12, title: 'Alpha' },
      { id: 7, title: 'Beta' },
    ])
  })

  it('dedupes repeated ids, keeping the first title seen', () => {
    const markdown = '[First](card:3) again [Second](card:3) and [C](card:4)'
    expect(parseCardLinks(markdown)).toEqual([
      { id: 3, title: 'First' },
      { id: 4, title: 'C' },
    ])
  })

  it('unescapes bracket-escaped titles back to [ and ]', () => {
    const markdown = 'Renderer escapes as [Foo \\[bar\\]](card:5).'
    expect(parseCardLinks(markdown)).toEqual([{ id: 5, title: 'Foo [bar]' }])
  })

  it('returns [] when no card links exist', () => {
    expect(parseCardLinks('see [docs](https://example.com) and plain text')).toEqual([])
  })
})
