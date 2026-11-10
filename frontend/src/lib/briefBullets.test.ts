// Tests for the per-bullet brief parser.
import { describe, expect, it } from 'vitest'
import { parseBriefBullets } from './briefBullets'

// Fixture mirrors the exact renderer grammar from brief_render.py: overview prose,
// then `## ` theme headings, each with `- ` bullets and optional `  - Related:` sub-lines.
const FIXTURE = `A detailed multi-sentence overview of the day. It can mention [Some Card](card:9) inline and span
multiple sentences or paragraphs.

## First theme heading

- New work on X as [Featured A](card:1) and [Featured B](card:2) show, combined into one bullet.
  - Related: [Neighbour P](card:7), [Neighbour Q](card:8)
- A separate point citing [Featured C](card:3).

## Second theme heading

- Another bullet [Featured D](card:4).
`

describe('parseBriefBullets', () => {
  it('captures the overview as everything before the first ## heading', () => {
    const result = parseBriefBullets(FIXTURE)
    expect(result.overview).toBe(
      'A detailed multi-sentence overview of the day. It can mention [Some Card](card:9) inline and span\nmultiple sentences or paragraphs.',
    )
  })

  it('parses two sections with correct headings and bullet counts', () => {
    const result = parseBriefBullets(FIXTURE)
    expect(result.sections).toHaveLength(2)
    expect(result.sections[0].heading).toBe('First theme heading')
    expect(result.sections[0].bullets).toHaveLength(2)
    expect(result.sections[1].heading).toBe('Second theme heading')
    expect(result.sections[1].bullets).toHaveLength(1)
  })

  it('collects multiple card links in one bullet, deduped by id', () => {
    const result = parseBriefBullets(FIXTURE)
    const bullet = result.sections[0].bullets[0]
    expect(bullet.markdown).toBe(
      'New work on X as [Featured A](card:1) and [Featured B](card:2) show, combined into one bullet.',
    )
    expect(bullet.cards).toEqual([
      { id: 1, title: 'Featured A' },
      { id: 2, title: 'Featured B' },
    ])
  })

  it('attaches a Related sub-line to the most recent bullet, not as its own bullet', () => {
    const result = parseBriefBullets(FIXTURE)
    const bullet = result.sections[0].bullets[0]
    expect(bullet.related).toEqual([
      { id: 7, title: 'Neighbour P' },
      { id: 8, title: 'Neighbour Q' },
    ])
  })

  it('gives bullets without a Related line an empty related array', () => {
    const result = parseBriefBullets(FIXTURE)
    const bullet = result.sections[0].bullets[1]
    expect(bullet.markdown).toBe('A separate point citing [Featured C](card:3).')
    expect(bullet.cards).toEqual([{ id: 3, title: 'Featured C' }])
    expect(bullet.related).toEqual([])

    const secondSectionBullet = result.sections[1].bullets[0]
    expect(secondSectionBullet.related).toEqual([])
  })

  it('unescapes bracket-escaped titles back to [ and ]', () => {
    const markdown = '## A section\n\n- See [Foo \\[bar\\]](card:5) for details.\n'
    const result = parseBriefBullets(markdown)
    expect(result.sections[0].bullets[0].cards).toEqual([{ id: 5, title: 'Foo [bar]' }])
  })

  it('returns the whole trimmed narrative as overview and no sections when there is no heading', () => {
    const markdown = '\n  Just a plain overview with no headings at all.  \n'
    const result = parseBriefBullets(markdown)
    expect(result.overview).toBe('Just a plain overview with no headings at all.')
    expect(result.sections).toEqual([])
  })

  it('keeps a heading with no bullets under it as a section with an empty bullets array', () => {
    const markdown = 'Overview text.\n\n## Empty section\n\n## Next section\n\n- One bullet [X](card:1).\n'
    const result = parseBriefBullets(markdown)
    expect(result.sections).toHaveLength(2)
    expect(result.sections[0]).toEqual({ heading: 'Empty section', bullets: [] })
    expect(result.sections[1].heading).toBe('Next section')
    expect(result.sections[1].bullets).toHaveLength(1)
  })
})
