// Unit tests for googleNewsUrl and siteFromUrl.
import { describe, expect, it } from 'vitest'
import { googleNewsUrl, siteFromUrl } from './googleNews'

describe('googleNewsUrl', () => {
  it('topic only: q contains only the topic term', () => {
    const url = googleNewsUrl('artificial intelligence')
    const params = new URL(url).searchParams
    expect(decodeURIComponent(params.get('q') ?? '')).toBe('artificial intelligence')
  })

  it('site only: q contains only the site: prefix', () => {
    const url = googleNewsUrl(undefined, 'example.com')
    const params = new URL(url).searchParams
    expect(decodeURIComponent(params.get('q') ?? '')).toBe('site:example.com')
  })

  it('both topic and site: q contains topic followed by site: term', () => {
    const url = googleNewsUrl('AI health', 'healthcareitnews.com')
    const params = new URL(url).searchParams
    expect(decodeURIComponent(params.get('q') ?? '')).toBe('AI health site:healthcareitnews.com')
  })

  it('empty topic and empty site: q is empty string', () => {
    const url = googleNewsUrl('', '')
    const params = new URL(url).searchParams
    expect(decodeURIComponent(params.get('q') ?? '')).toBe('')
  })

  it('whitespace-only topic is trimmed and treated as absent', () => {
    const url = googleNewsUrl('   ', 'example.com')
    const params = new URL(url).searchParams
    expect(decodeURIComponent(params.get('q') ?? '')).toBe('site:example.com')
  })

  it('fixed locale params are always present', () => {
    const url = googleNewsUrl('news')
    const params = new URL(url).searchParams
    expect(params.get('hl')).toBe('en-US')
    expect(params.get('gl')).toBe('US')
    expect(params.get('ceid')).toBe('US:en')
  })

  it('returns a URL rooted at news.google.com/rss/search', () => {
    const url = googleNewsUrl('test')
    const parsed = new URL(url)
    expect(parsed.hostname).toBe('news.google.com')
    expect(parsed.pathname).toBe('/rss/search')
  })
})

describe('siteFromUrl', () => {
  it('strips www. from a standard URL', () => {
    expect(siteFromUrl('https://www.healthcareitnews.com/topics/ai')).toBe('healthcareitnews.com')
  })

  it('returns hostname unchanged when there is no www. prefix', () => {
    expect(siteFromUrl('https://example.com/page')).toBe('example.com')
  })

  it('returns empty string for a bad (unparseable) URL', () => {
    expect(siteFromUrl('not a url')).toBe('')
  })

  it('returns empty string for an empty string', () => {
    expect(siteFromUrl('')).toBe('')
  })

  it('handles subdomain other than www. without stripping it', () => {
    expect(siteFromUrl('https://blog.example.com/post')).toBe('blog.example.com')
  })
})
