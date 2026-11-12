// Tests for the typed client: JSON handling, query strings, and the mapping of every failure to
// an ApiError with a human message.
import { afterEach, describe, expect, it } from 'vitest'
import { createThread, getBrief, getEngines, getFeed, queryString, request } from './client'
import { ApiError, errorMessage, extractDetail, messageForStatus } from './errors'
import { setFetchForTesting } from './transport'

afterEach(() => setFetchForTesting(null))

/** Make the client receive one canned response. */
function reply(status: number, body: unknown, raw = false): void {
  setFetchForTesting(async () => new Response(raw ? (body as string) : body === null ? null : JSON.stringify(body), { status }))
}

describe('request', () => {
  it('parses a JSON reply', async () => {
    reply(200, { ok: true })
    await expect(request('GET', '/x')).resolves.toEqual({ ok: true })
  })

  it('resolves null for an empty 204 reply', async () => {
    reply(204, null)
    await expect(request('POST', '/x', {})).resolves.toBeNull()
  })

  it('uses a 4xx string detail as the message', async () => {
    reply(409, { detail: 'No vault folder is configured. Set one in Settings.' })
    await expect(request('POST', '/items/1/file', {})).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      kind: 'http',
      message: 'No vault folder is configured. Set one in Settings.',
    })
  })

  it('joins FastAPI validation errors into one message', async () => {
    reply(422, { detail: [{ msg: 'field required' }, { msg: 'value is not a valid url' }] })
    await expect(request('POST', '/capture', {})).rejects.toMatchObject({ status: 422, message: 'field required; value is not a valid url' })
  })

  it('hides a 5xx detail behind a plain message but keeps it for diagnosis', async () => {
    reply(500, { detail: 'Traceback (most recent call last)…' })
    const error = (await request('GET', '/today').catch((cause: unknown) => cause)) as ApiError
    expect(error.message).toBe(messageForStatus(500))
    expect(error.detail).toContain('Traceback')
  })

  it('maps a refused connection to a network error', async () => {
    setFetchForTesting(async () => {
      throw new TypeError('Failed to fetch')
    })
    const error = (await request('GET', '/today').catch((cause: unknown) => cause)) as ApiError
    expect(error.kind).toBe('network')
    expect(error.status).toBe(0)
    expect(error.message).toMatch(/not reachable/)
  })

  it('maps an aborted request to kind aborted', async () => {
    setFetchForTesting(async () => {
      throw new DOMException('Aborted', 'AbortError')
    })
    await expect(request('GET', '/today')).rejects.toMatchObject({ kind: 'aborted' })
  })

  it('reports an unreadable success body as a parse error', async () => {
    reply(200, '<html>proxy page</html>', true)
    await expect(request('GET', '/today')).rejects.toMatchObject({ kind: 'parse' })
  })

  it('uses a plain-text error body as the detail', async () => {
    reply(400, 'Bad thing', true)
    await expect(request('GET', '/x')).rejects.toMatchObject({ status: 400, message: 'Bad thing' })
  })
})

describe('helpers', () => {
  it('builds query strings from defined values only', () => {
    expect(queryString({ section: 'health', saved: true, from_user: false, q: '', before: undefined, limit: 50 })).toBe('?section=health&saved=true&limit=50')
    expect(queryString({})).toBe('')
  })

  it('extracts details from the shapes servers send', () => {
    expect(extractDetail({ detail: 'x' })).toBe('x')
    expect(extractDetail({ message: 'y' })).toBe('y')
    expect(extractDetail(null)).toBeNull()
    expect(extractDetail({ detail: [{ nope: 1 }] })).toBeNull()
  })

  it('gives a message for any thrown value', () => {
    expect(errorMessage(new ApiError('A', { status: 404, kind: 'http', path: '/' }))).toBe('A')
    expect(errorMessage(new Error('B'))).toBe('B')
    expect(errorMessage('weird')).toBe('Something went wrong.')
  })

  it('has a message for each common status', () => {
    for (const status of [400, 401, 404, 409, 429, 503, 500, 418]) expect(messageForStatus(status)).toBeTruthy()
  })
})

describe('endpoint shapes', () => {
  it('sends feed filters as query parameters', async () => {
    let url = ''
    setFetchForTesting(async (input) => {
      url = input
      return new Response(JSON.stringify({ items: [], next_before: null, total: 0 }), { status: 200 })
    })
    await getFeed({ section: 'health', tier: 'all', saved: true, before: '2026-11-12T10:00:00Z' })
    expect(url).toBe('/api/radar/feed?section=health&tier=all&saved=true&before=2026-11-12T10%3A00%3A00Z')
  })

  it('accepts a brief either bare or wrapped', async () => {
    reply(200, { brief: { day: '2026-11-12', sections: [] } })
    await expect(getBrief('2026-11-12')).resolves.toMatchObject({ day: '2026-11-12' })
    reply(200, { day: '2026-11-11', sections: [] })
    await expect(getBrief('2026-11-11')).resolves.toMatchObject({ day: '2026-11-11' })
  })

  it('accepts engines as a list or wrapped in {engines}', async () => {
    reply(200, [{ id: 'a' }])
    await expect(getEngines()).resolves.toEqual([{ id: 'a' }])
    reply(200, { engines: [{ id: 'b' }] })
    await expect(getEngines()).resolves.toEqual([{ id: 'b' }])
  })

  it('returns thread and messages from POST /threads', async () => {
    reply(200, { thread: { id: 5 }, messages: [{ id: 1 }] })
    await expect(createThread({ item_id: 3 })).resolves.toEqual({ thread: { id: 5 }, messages: [{ id: 1 }] })
  })
})

describe('validation messages', () => {
  it('says "That address is too long." for the 2048-character limit, in either error shape', () => {
    expect(extractDetail({ detail: 'String should have at most 2048 characters' })).toBe('That address is too long.')
    expect(extractDetail({ detail: [{ loc: ['body', 'url'], msg: 'String should have at most 2048 characters' }] })).toBe('That address is too long.')
    expect(extractDetail({ detail: 'String should have at most 200 characters' })).toBe('String should have at most 200 characters')
  })
})
