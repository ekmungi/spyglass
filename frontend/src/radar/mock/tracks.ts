// Sample-mode routes for "follow more like this": suggestions for an item or an address, and the
// followed topics (list, create, edit, stop). Answers mirror the service, including its failures.
import type { RadarItem, Track, TrackCreateBody, TrackPatchBody } from '../api/types'
import { SECTION_LABELS } from './items'
import { recentFor, similarTo, suggestionsFor } from './trackData'
import { addCapturedItem, mockState } from './store'

const SUGGEST_MS = 2200
const CREATE_MS = 1500

/** A JSON Response with the given status. */
function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Wait `ms`, rejecting with an AbortError if the signal fires first. */
function wait(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    })
  })
}

/** True for addresses the service refuses to read: local names and private network ranges. */
function isPrivateHost(url: URL): boolean {
  const host = url.hostname
  return host === 'localhost' || host.endsWith('.local') || /^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host) || host === '[::1]'
}

/** The address as a URL when it is a well-formed http(s) address, else null. */
function parseHttpUrl(address: string): URL | null {
  if (!/^https?:\/\//i.test(address)) return null
  try {
    return new URL(address)
  } catch {
    return null
  }
}

/** The suggestion reply for one item. */
function suggestionReply(item: RadarItem, mode: 'ai' | 'basic') {
  const current = mockState()
  return { mode, suggestions: suggestionsFor(item, current.tracks), similar: similarTo(item, current.items) }
}

/** POST /items/{id}/track/suggest and POST /track/suggest. */
export async function suggestRoute(parts: string[], body: Record<string, unknown>, signal?: AbortSignal | null): Promise<Response> {
  const current = mockState()
  if (parts[0] === 'items') {
    const item = current.items.find((entry) => entry.id === Number(parts[1]))
    if (!item) return json({ detail: 'Not found' }, 404)
    await wait(SUGGEST_MS, signal)
    return json(suggestionReply(item, 'ai'))
  }
  const address = String(body.url ?? '')
  const parsed = parseHttpUrl(address)
  if (!parsed) return json({ detail: 'Enter a full web address starting with http:// or https://.' }, 422)
  if (isPrivateHost(parsed)) return json({ detail: 'That address points to a private network, which Spyglass will not read.' }, 422)
  await wait(SUGGEST_MS, signal)
  const item = current.items.find((entry) => entry.url === address) ?? addCapturedItem(address, undefined)
  return json({ ...suggestionReply(item, /basic/i.test(address) ? 'basic' : 'ai'), item })
}

/** GET/POST/PATCH/DELETE /tracks. */
export async function tracksRoute(method: string, parts: string[], body: Record<string, unknown>, signal?: AbortSignal | null): Promise<Response | null> {
  const current = mockState()
  const withRecent = (track: Track): Track => ({ ...track, recent: recentFor(track.query, current.items) })
  if (method === 'GET' && parts.length === 1) return json({ tracks: current.tracks.map(withRecent) })
  if (method === 'POST' && parts.length === 1) {
    const fields = body as unknown as TrackCreateBody
    const label = String(fields.label ?? '').trim()
    const query = String(fields.query ?? '').trim()
    if (!label || !query) return json({ detail: 'A topic needs a name and a search query.' }, 422)
    if (current.tracks.some((track) => track.query.toLowerCase() === query.toLowerCase())) return json({ detail: `You already follow "${label}".` }, 409)
    // A label containing "fail" lets sample mode show a per-topic failure.
    if (/\bfail\b/i.test(label)) return json({ detail: 'The first search for this topic could not be run (sample error).' }, 422)
    await wait(CREATE_MS, signal)
    const found = recentFor(query, current.items)
    const created: Track = {
      id: current.nextTrackId++,
      label,
      query,
      section: fields.section ?? '',
      section_label: current.items.find((item) => item.section === fields.section)?.section_label ?? '',
      kind: fields.kind ?? 'topic',
      active: true,
      created_at: new Date().toISOString(),
      from_item_id: fields.from_item_id ?? null,
      last_run_at: new Date().toISOString(),
      last_new: found.length + 1,
      recent: found,
    }
    current.tracks = [...current.tracks, created]
    return json({ ...created, new_items: created.last_new, topic_added: false }, 201)
  }
  const target = current.tracks.find((track) => track.id === Number(parts[1]))
  if (!target) return json({ detail: 'Not found' }, 404)
  if (method === 'PATCH') {
    const patch = body as TrackPatchBody
    if (Object.keys(patch).length === 0) return json({ detail: 'Nothing to change.' }, 422)
    const updated: Track = { ...target, ...patch, ...(patch.section !== undefined ? { section_label: SECTION_LABELS[patch.section] ?? '' } : {}) }
    current.tracks = current.tracks.map((track) => (track.id === target.id ? updated : track))
    return json(withRecent(updated))
  }
  if (method === 'DELETE') {
    current.tracks = current.tracks.filter((track) => track.id !== target.id)
    return json({ deleted: target.id })
  }
  return null
}
