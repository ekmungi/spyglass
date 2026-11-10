// Tests for the feed API wrappers: getFeeds, addFeed, patchFeed, deleteFeed,
// importFeeds, exportFeeds, discoverFeeds, NotAFeedError.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FeedData } from './types'
import { NotAFeedError, addFeed, deleteFeed, discoverFeeds, exportFeeds, getFeeds, importFeeds, patchFeed } from './api'

const FEED: FeedData = {
  id: 1,
  feed_url: 'https://example.com/feed.xml',
  name: 'Example',
  name_overridden: false,
  kind: 'rss',
  enabled: true,
  last_fetch_status: 'ok',
  last_fetch_at: '2026-06-29T10:00:00Z',
  last_error: null,
  item_count: 10,
  added_via: 'import',
}

function stubFetch(body: unknown, status = 200, asText = false) {
  return vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
    if (asText) {
      return new Response(body as string, { status })
    }
    return new Response(JSON.stringify(body), { status })
  })
}

describe('getFeeds', () => {
  beforeEach(() => vi.stubGlobal('fetch', stubFetch([FEED])))
  afterEach(() => vi.unstubAllGlobals())

  it('GET /api/feeds returns FeedData[]', async () => {
    const result = await getFeeds()
    expect(result).toEqual([FEED])
    expect(vi.mocked(fetch)).toHaveBeenCalledWith('/api/feeds', undefined)
  })
})

describe('addFeed', () => {
  beforeEach(() => vi.stubGlobal('fetch', stubFetch(FEED)))
  afterEach(() => vi.unstubAllGlobals())

  it('POST /api/feeds with url body', async () => {
    const result = await addFeed('https://example.com/feed.xml')
    expect(result).toEqual(FEED)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/feeds')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ url: 'https://example.com/feed.xml' })
  })

  it('throws NotAFeedError when the 422 body has kind=not_a_feed', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch({ detail: { kind: 'not_a_feed', url: 'https://example.com' } }, 422),
    )
    await expect(addFeed('https://example.com')).rejects.toBeInstanceOf(NotAFeedError)
  })

  it('shows the reason when the site refused Spyglass', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch(
        { detail: { kind: 'blocked', url: 'https://x.test/feed', reason: 'The site refused Spyglass.' } },
        422,
      ),
    )
    await expect(addFeed('https://x.test/feed')).rejects.toThrow('The site refused Spyglass.')
  })

  it('NotAFeedError carries the resolved url from the response body', async () => {
    const resolvedUrl = 'https://example.com/resolved'
    vi.stubGlobal(
      'fetch',
      stubFetch({ detail: { kind: 'not_a_feed', url: resolvedUrl } }, 422),
    )
    let caught: unknown
    try {
      await addFeed('https://example.com')
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(NotAFeedError)
    expect((caught as NotAFeedError).url).toBe(resolvedUrl)
  })

  it('throws a generic Error on non-422 failures', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('err', { status: 500 })))
    await expect(addFeed('https://example.com')).rejects.toThrow(/500/)
  })
})

describe('discoverFeeds', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('POST /api/feeds/discover with url and depth, returns candidates', async () => {
    const mockResult = {
      candidates: [
        { feed_url: 'https://ex.com/feed.xml', name: 'Ex Feed', kind: 'rss', already_subscribed: false },
      ],
      reason: null,
    }
    vi.stubGlobal('fetch', stubFetch(mockResult))

    const result = await discoverFeeds('https://ex.com', 'shallow')

    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/feeds/discover')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ url: 'https://ex.com', depth: 'shallow' })
    expect(result.candidates).toHaveLength(1)
    expect(result.candidates[0].feed_url).toBe('https://ex.com/feed.xml')
    expect(result.reason).toBeNull()
  })

  it('passes depth="deep" in the request body', async () => {
    vi.stubGlobal('fetch', stubFetch({ candidates: [], reason: 'No feeds' }))

    await discoverFeeds('https://ex.com', 'deep')

    const init = vi.mocked(fetch).mock.calls[0][1]
    expect(JSON.parse(String(init?.body))).toMatchObject({ depth: 'deep' })
  })
})

describe('patchFeed', () => {
  beforeEach(() => vi.stubGlobal('fetch', stubFetch({ ...FEED, enabled: false })))
  afterEach(() => vi.unstubAllGlobals())

  it('PATCH /api/feeds/:id with patch body', async () => {
    const result = await patchFeed(1, { enabled: false })
    expect(result.enabled).toBe(false)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/feeds/1')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(String(init?.body))).toEqual({ enabled: false })
  })
})

describe('deleteFeed', () => {
  beforeEach(() =>
    vi.stubGlobal('fetch', stubFetch({ deleted: true, cards_removed: 3 })),
  )
  afterEach(() => vi.unstubAllGlobals())

  it('DELETE /api/feeds/:id returns deleted + cards_removed', async () => {
    const result = await deleteFeed(1)
    expect(result).toEqual({ deleted: true, cards_removed: 3 })
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/feeds/1')
    expect(init?.method).toBe('DELETE')
  })
})

describe('importFeeds', () => {
  beforeEach(() => vi.stubGlobal('fetch', stubFetch({ added: 2, skipped: 0 })))
  afterEach(() => vi.unstubAllGlobals())

  it('POST /api/feeds/import with raw text/plain body', async () => {
    const result = await importFeeds('<opml/>')
    expect(result).toEqual({ added: 2, skipped: 0 })
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/feeds/import')
    expect(init?.method).toBe('POST')
    expect((init?.headers as Record<string, string>)['Content-Type']).toBe('text/plain')
    expect(init?.body).toBe('<opml/>')
  })
})

describe('exportFeeds', () => {
  beforeEach(() =>
    vi.stubGlobal('fetch', stubFetch('<?xml version="1.0"?><opml/>', 200, true)),
  )
  afterEach(() => vi.unstubAllGlobals())

  it('GET /api/feeds/export?format=opml returns text string', async () => {
    const result = await exportFeeds('opml')
    expect(result).toBe('<?xml version="1.0"?><opml/>')
    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toBe('/api/feeds/export?format=opml')
  })

  it('GET /api/feeds/export?format=markdown', async () => {
    vi.stubGlobal('fetch', stubFetch('# Feeds', 200, true))
    const result = await exportFeeds('markdown')
    expect(result).toBe('# Feeds')
    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toBe('/api/feeds/export?format=markdown')
  })
})
