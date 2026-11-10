// Tests for addFeed's optional name param.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { addFeed } from './api'

// Capture fetch calls so we can assert the request body.
let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const OK_FEED = {
  id: 1,
  feed_url: 'https://example.com/feed.xml',
  name: 'Example',
  name_overridden: false,
  kind: 'rss',
  enabled: true,
  last_fetch_status: null,
  last_fetch_at: null,
  last_error: null,
  item_count: 0,
  added_via: 'manual',
}

function makeOkResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response
}

describe('addFeed – name parameter', () => {
  it('posts {url} when name is omitted', async () => {
    fetchMock.mockResolvedValue(makeOkResponse(OK_FEED))

    await addFeed('https://example.com/feed.xml')

    expect(fetchMock).toHaveBeenCalledOnce()
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const body = JSON.parse(init.body as string) as Record<string, unknown>
    expect(body).toEqual({ url: 'https://example.com/feed.xml' })
    expect(body).not.toHaveProperty('name')
  })

  it('posts {url, name} when name is provided', async () => {
    fetchMock.mockResolvedValue(makeOkResponse(OK_FEED))

    await addFeed('https://example.com/feed.xml', 'My Feed')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const body = JSON.parse(init.body as string) as Record<string, unknown>
    expect(body).toEqual({ url: 'https://example.com/feed.xml', name: 'My Feed' })
  })

  it('posts {url} when name is an empty string (treated as absent)', async () => {
    fetchMock.mockResolvedValue(makeOkResponse(OK_FEED))

    await addFeed('https://example.com/feed.xml', '')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const body = JSON.parse(init.body as string) as Record<string, unknown>
    expect(body).toEqual({ url: 'https://example.com/feed.xml' })
    expect(body).not.toHaveProperty('name')
  })
})
