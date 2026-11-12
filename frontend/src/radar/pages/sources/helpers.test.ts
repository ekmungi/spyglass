// Tests for the shared helpers behind the secondary pages: failure wording, reply normalisers,
// date wording, and the older-endpoint request wrapper.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import { toCollectorRow, toFeedRow } from './api'
import { collectorStatus, describeFailure, feedStatus, isNotConfigured, newItemsText } from './describe'
import { formatDay, formatUpcoming, formatWhen, isWithinDays, parseWhen } from './format'
import { requestJson } from './http'

afterEach(() => vi.unstubAllGlobals())

describe('describeFailure', () => {
  it.each([
    ['HTTPError: 403 Client Error: Forbidden', 'The site refused access.'],
    ['ReadTimeout: HTTPSConnectionPool(host=x): Read timed out.', 'The site did not answer in time.'],
    ['SSLError: certificate verify failed', "The site's security certificate could not be verified."],
    ['ConnectionError: getaddrinfo failed', 'Spyglass could not reach the site.'],
    ['xml.sax.SAXParseException: not well-formed', 'The address did not return a readable feed.'],
  ])('turns %s into a sentence', (raw, sentence) => {
    expect(describeFailure(raw)).toBe(sentence)
  })

  it('keeps a message that already reads as a sentence', () => {
    expect(describeFailure('The feed returned HTTP 404 for the last three attempts.')).toBe('The feed returned HTTP 404 for the last three attempts.')
  })

  it('never returns a bare code and handles a missing reason', () => {
    expect(describeFailure(null)).toBe('The last attempt failed, and no reason was recorded.')
    expect(describeFailure('WeirdError: boom')).toBe('The last attempt failed: boom.')
  })
})

describe('row normalisers', () => {
  it('reads the older feed shape', () => {
    const row = toFeedRow({ id: 3, name: 'A', feed_url: 'https://a/feed', enabled: false, last_fetch_status: 'error', last_error: 'x', item_count: 7, last_fetch_at: '2026-01-01T00:00:00Z' })
    expect(row).toMatchObject({ id: 3, url: 'https://a/feed', enabled: false, status: 'error', error: 'x', items: 7 })
  })

  it('reads the shared sample shape and survives missing fields', () => {
    expect(toFeedRow({ id: 1, name: 'B', url: 'https://b', status: 'ok', last_fetched_at: 'z', new_items: 2 })).toMatchObject({ url: 'https://b', status: 'ok', items: 2 })
    expect(toFeedRow(null)).toMatchObject({ id: 0, name: 'Untitled feed', status: 'never', enabled: true })
  })

  it('reads collectors from either naming', () => {
    expect(toCollectorRow({ key: 'hn', label: 'HN', status: 'ok', last_run: 'a', new_items: 4 })).toMatchObject({ key: 'hn', lastRun: 'a', newItems: 4 })
    expect(toCollectorRow({ name: 'news', status: 'weird' })).toMatchObject({ key: 'news', label: 'news', status: 'never' })
  })
})

describe('status wording', () => {
  const base = { id: 1, name: 'F', url: '', lastFetchAt: null, items: null }
  it('describes feeds', () => {
    expect(feedStatus({ ...base, enabled: false, status: 'ok', error: null }).text).toBe('Switched off')
    expect(feedStatus({ ...base, enabled: true, status: 'never', error: null }).text).toBe('Not fetched yet')
    expect(feedStatus({ ...base, enabled: true, status: 'ok', error: null })).toEqual({ text: 'Working', tone: 'ok' })
    expect(feedStatus({ ...base, enabled: true, status: 'error', error: null }).tone).toBe('problem')
  })

  it('describes collectors', () => {
    const row = { key: 'k', label: 'K', detail: null, lastRun: null, newItems: null, enabled: null }
    expect(isNotConfigured(undefined)).toBe(true)
    expect(collectorStatus({ ...row, status: 'skipped' }).text).toBe('Not configured')
    expect(collectorStatus({ ...row, status: 'never' }).text).toBe('Has not run yet')
    expect(collectorStatus({ ...row, status: 'ok' }).tone).toBe('ok')
    expect(newItemsText(0)).toBe('nothing new')
    expect(newItemsText(1)).toBe('1 new item')
    expect(newItemsText(null)).toBe('')
  })
})

describe('date wording', () => {
  const now = new Date('2026-11-12T12:00:00')
  it('parses timestamps without a zone as UTC and rejects junk', () => {
    expect(parseWhen('2026-11-12T10:00:00')?.toISOString()).toBe('2026-11-12T10:00:00.000Z')
    expect(parseWhen('nonsense')).toBeNull()
    expect(parseWhen(null)).toBeNull()
  })

  it('says today, yesterday and tomorrow', () => {
    expect(formatWhen(new Date('2026-11-12T08:00:00').toISOString(), now)).toMatch(/^today at/)
    expect(formatWhen(new Date('2026-11-11T08:00:00').toISOString(), now)).toMatch(/^yesterday at/)
    expect(formatUpcoming(new Date('2026-11-13T06:30:00').toISOString(), now)).toMatch(/^tomorrow at/)
    expect(formatDay(null)).toBe('')
    expect(formatDay(new Date('2025-03-05T12:00:00').toISOString(), now)).toContain('2025')
  })

  it('knows what happened in the last week', () => {
    expect(isWithinDays(new Date('2026-11-09T12:00:00').toISOString(), 7, now)).toBe(true)
    expect(isWithinDays(new Date('2026-10-01T12:00:00').toISOString(), 7, now)).toBe(false)
    expect(isWithinDays(null, 7, now)).toBe(false)
  })
})

describe('requestJson', () => {
  it('returns parsed JSON on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: 1 }), { status: 200 })))
    await expect(requestJson('GET', '/api/settings')).resolves.toEqual({ ok: 1 })
  })

  it('uses the reason a feed endpoint gives for a 422', async () => {
    const body = { detail: { kind: 'not_a_feed', url: 'u', reason: 'That address is a web page, not a feed.' } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 422 })))
    await expect(requestJson('POST', '/api/feeds', { url: 'u' })).rejects.toMatchObject({ status: 422, message: 'That address is a web page, not a feed.' })
  })

  it('explains an unreachable service and a server fault in words', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(requestJson('GET', '/api/settings')).rejects.toBeInstanceOf(ApiError)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('boom', { status: 500 })))
    await expect(requestJson('GET', '/api/settings')).rejects.toMatchObject({ message: expect.stringContaining('Try again') })
  })
})
