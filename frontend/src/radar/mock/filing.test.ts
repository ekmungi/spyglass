// Tests for the sample-mode To file queue: the shapes the real service is expected to send, so sample
// mode and the interface agree with it.
import { beforeEach, describe, expect, it } from 'vitest'
import { mockFetch, resetMockState } from '.'

beforeEach(() => resetMockState())

/** Call the sample service the way the client does. */
async function call(method: string, path: string, body?: unknown) {
  const response = await mockFetch(`/api/radar${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body) })
  return { status: response.status, json: (await response.json().catch(() => null)) as Record<string, unknown> | null }
}

describe('sample To file queue', () => {
  it('queues an item, lists it with its choices, marks it in the feed and takes it out again', async () => {
    const queued = await call('POST', '/items/101/file', { kind: 'learning', project: 'Imaging AI', note: 'for Friday' })
    expect(queued).toEqual({ status: 200, json: { item_id: 101, filing: 'waiting', count: 1 } })
    const queue = await call('GET', '/filing')
    expect(queue.json).toMatchObject({ count: 1, waiting: [{ kind: 'learning', project: 'Imaging AI', note: 'for Friday', item: { id: 101, filing: 'waiting' } }] })
    const feed = await call('GET', '/feed?filing=waiting')
    expect((feed.json?.items as { id: number }[]).map((item) => item.id)).toEqual([101])
    expect(await call('DELETE', '/items/101/file')).toEqual({ status: 200, json: { item_id: 101, filing: null, count: 0 } })
    expect((await call('GET', '/feed?filing=waiting')).json?.items).toEqual([])
  })

  it('answers 404 for an unknown item and 409 for one that is already filed', async () => {
    expect((await call('POST', '/items/99999/file', {})).status).toBe(404)
    const feed = await call('GET', '/feed?filed=true')
    const filed = (feed.json?.items as { id: number }[])[0]
    expect((await call('POST', `/items/${filed.id}/file`, {})).status).toBe(409)
  })

  it('previews the batch request without titles, and refuses to open an empty queue', async () => {
    expect((await call('POST', '/filing/open', {})).json).toEqual({ detail: 'Nothing is waiting to be filed.' })
    await call('POST', '/items/101/file', {})
    await call('POST', '/items/102/file', {})
    const preview = await call('POST', '/filing/preview', {})
    expect(String(preview.json?.text)).toContain('2 items are waiting to be filed')
    expect(String(preview.json?.text)).toContain('spyglass-file')
    expect(preview.json).toMatchObject({ available: true, reason: null })
    expect((await call('POST', '/filing/open', {})).json).toEqual({ opened: true, delivery: 'link' })
  })
})
