// Tests for the origin label: brand names with sensible fallbacks.
import { describe, expect, it } from 'vitest'
import { makeCard } from '../test/fixtures'
import { originLabel, sourceLabel, youtubeVideoId } from './source'

describe('originLabel', () => {
  it('passes human feed titles through untouched', () => {
    expect(originLabel(makeCard({ origin: 'NVIDIA Technical Blog' }))).toBe(
      'NVIDIA Technical Blog',
    )
  })

  it('turns domains into brand names, dropping subdomains and TLDs', () => {
    expect(originLabel(makeCard({ origin: 'forbes.com' }))).toBe('Forbes')
    expect(originLabel(makeCard({ origin: null, url: 'https://developer.nvidia.com/blog/x' }))).toBe(
      'NVIDIA',
    )
    expect(originLabel(makeCard({ origin: 'www.youtube.com' }))).toBe('YouTube')
    expect(originLabel(makeCard({ origin: null, url: 'https://arxiv.org/abs/1' }))).toBe('arXiv')
  })

  it('handles country-code multi-part TLDs', () => {
    expect(originLabel(makeCard({ origin: 'bbc.co.uk' }))).toBe('BBC')
  })

  it('falls back to the collector name when the URL is unparsable', () => {
    expect(originLabel(makeCard({ origin: null, url: 'not a url', source: 'rss' }))).toBe('rss')
  })
})

describe('sourceLabel', () => {
  it('appends the hosting platform when it adds information', () => {
    expect(
      sourceLabel(
        makeCard({ origin: 'Stanford Medicine', url: 'https://www.youtube.com/watch?v=abc123xyz' }),
      ),
    ).toBe('Stanford Medicine · YouTube')
  })

  it('does not repeat a platform the label already implies', () => {
    expect(
      sourceLabel(makeCard({ origin: 'youtube.com', url: 'https://www.youtube.com/watch?v=a1b2c3d' })),
    ).toBe('YouTube')
  })
})

describe('youtubeVideoId', () => {
  it('extracts ids from watch, short-link, and shorts urls', () => {
    expect(youtubeVideoId('https://www.youtube.com/watch?v=dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ')
    expect(youtubeVideoId('https://youtu.be/dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ')
    expect(youtubeVideoId('https://www.youtube.com/shorts/AbC-123_xy')).toBe('AbC-123_xy')
    expect(youtubeVideoId('https://example.com/watch?v=nope')).toBe(null)
  })
})
