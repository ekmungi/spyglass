// Sample-mode fixtures for "follow more like this": they must answer with the service's shapes and
// failures so the whole flow can be clicked through with ?mock=1.
import { beforeEach, describe, expect, it } from 'vitest'
import type { Track, TrackCreated, TrackSuggestResponse } from '../api/types'
import { mockFetch, resetMockState } from '.'

async function call<T>(method: string, path: string, body?: unknown): Promise<{ status: number; data: T }> {
  const response = await mockFetch(`/api/radar${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body) })
  const text = await response.text()
  return { status: response.status, data: (text ? JSON.parse(text) : null) as T }
}

beforeEach(() => resetMockState())

describe('sample tracks', () => {
  it('lists the seeded topics with their latest items', async () => {
    const { status, data } = await call<{ tracks: Track[] }>('GET', '/tracks')
    expect(status).toBe(200)
    expect(data.tracks.map((track) => track.label)).toEqual(['Real-time polyp detection', 'Agent harnesses'])
    expect(data.tracks[0].recent.length).toBeGreaterThan(0)
    expect(data.tracks[0].last_run_at).not.toBeNull()
  })

  it('suggests topics and organisations for an item, with similar items that exclude the item itself', async () => {
    const { status, data } = await call<TrackSuggestResponse>('POST', '/items/102/track/suggest', {})
    expect(status).toBe(200)
    expect(data.mode).toBe('ai')
    expect(data.suggestions.map((line) => line.kind)).toContain('organisation')
    expect(data.suggestions.every((line) => line.label && line.query && line.why && line.section_label)).toBe(true)
    expect(data.similar.length).toBeGreaterThan(0)
    expect(data.similar.length).toBeLessThanOrEqual(8)
    expect(data.similar.some((item) => item.id === 102)).toBe(false)
  }, 10_000)

  it('answers 404 for an unknown item and 422 for a private or malformed address', async () => {
    expect((await call('POST', '/items/9999/track/suggest', {})).status).toBe(404)
    const refused = await call<{ detail: string }>('POST', '/track/suggest', { url: 'http://192.168.1.4/page' })
    expect(refused.status).toBe(422)
    expect(refused.data.detail).toMatch(/private network/)
    expect((await call('POST', '/track/suggest', { url: 'not a link' })).status).toBe(422)
  })

  it('reads an address and returns the item it became', async () => {
    const { status, data } = await call<TrackSuggestResponse>('POST', '/track/suggest', { url: 'https://example.org/a-new-page' })
    expect(status).toBe(200)
    expect(data.item?.url).toBe('https://example.org/a-new-page')
    expect(data.suggestions.length).toBeGreaterThan(0)
  }, 10_000)

  it('creates a topic (201 with new_items), then reports it as already followed and refuses a duplicate with 409', async () => {
    const body = { label: 'Polyp detection clearance', query: 'polyp detection FDA clearance', section: 'health', kind: 'topic', from_item_id: 102 }
    const created = await call<TrackCreated>('POST', '/tracks', body)
    expect(created.status).toBe(201)
    expect(created.data.new_items).toBeGreaterThan(0)
    expect(created.data.from_item_id).toBe(102)
    const again = await call<{ detail: string }>('POST', '/tracks', body)
    expect(again.status).toBe(409)
    expect(again.data.detail).toMatch(/already follow/)
    const suggested = await call<TrackSuggestResponse>('POST', '/items/102/track/suggest', {})
    expect(suggested.data.suggestions.find((line) => line.query === body.query)?.already_followed).toBe(true)
  }, 15_000)

  it('fails a topic named "fail" with a readable 422 so one failure can be shown', async () => {
    const { status, data } = await call<{ detail: string }>('POST', '/tracks', { label: 'This will fail', query: 'q', section: 'health', kind: 'topic' })
    expect(status).toBe(422)
    expect(data.detail).toMatch(/could not be run/)
  })

  it('edits, pauses and deletes a topic', async () => {
    const patched = await call<Track>('PATCH', '/tracks/1', { label: 'Polyp AI', active: false })
    expect(patched.data).toMatchObject({ label: 'Polyp AI', active: false })
    expect((await call('PATCH', '/tracks/1', {})).status).toBe(422)
    expect((await call<{ deleted: number }>('DELETE', '/tracks/2')).data).toEqual({ deleted: 2 })
    const listed = await call<{ tracks: Track[] }>('GET', '/tracks')
    expect(listed.data.tracks.map((track) => track.id)).toEqual([1])
    expect((await call('DELETE', '/tracks/99')).status).toBe(404)
  })
})
