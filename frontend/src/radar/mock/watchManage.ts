// Sample-mode routes for whole-group changes on the Watch page and for the AI review of the register.
// They change the in-memory register, so a click-through behaves like the service.
import type { WatchApplyBody, WatchEntity, WatchGroupBody, WatchReview } from '../api/types'
import { groupWatch } from './catalog'
import { mockState } from './store'

const REVIEW_MS = 2400
const MAX_GROUP_NAME = 60

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

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

const register = () => {
  const current = mockState()
  return groupWatch(current.watch, current.items)
}

/** A group name as the service stores it: "Other" means no category. */
function storedName(value: unknown): string | null {
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text || text.length > MAX_GROUP_NAME || /[\r\n\t]/.test(text)) return null
  return text.toLowerCase() === 'other' ? '' : text
}

const inGroup = (entity: WatchEntity, name: string) => (entity.category || 'Other').toLowerCase() === name.toLowerCase()

/** PATCH /watch/groups: pause, resume, rename, move or remove every followed name of a group. */
function groupRoute(body: WatchGroupBody): Response {
  const current = mockState()
  const members = current.watch.filter((entity) => inGroup(entity, body.category) && entity.status !== 'suggested')
  if (members.length === 0) return json({ detail: `There is no group called ${body.category}.` }, 404)
  if (body.action === 'rename' || body.action === 'move') {
    const to = storedName(body.to)
    if (to === null) return json({ detail: 'A group name must be one line of up to 60 characters.' }, 422)
    current.watch = current.watch.map((entity) => (inGroup(entity, body.category) ? { ...entity, category: to } : entity))
    return json({ ...register(), removed: [] })
  }
  if (body.action === 'remove') {
    const removed = members.map((entity) => ({ ...entity, links: [] }))
    current.watch = current.watch.filter((entity) => !members.includes(entity))
    return json({ ...register(), removed })
  }
  const from = body.action === 'pause' ? 'active' : 'muted'
  const status = body.action === 'pause' ? 'muted' : 'active'
  current.watch = current.watch.map((entity) => (members.includes(entity) && entity.status === from ? { ...entity, status } : entity))
  return json({ ...register(), removed: [] })
}

/** POST /watch/groups/restore: put removed names back (names already present are skipped). */
function restoreRoute(entries: (WatchEntity & { links?: unknown })[]): Response {
  const current = mockState()
  const names = new Set(current.watch.map((entity) => entity.name.toLowerCase()))
  let restored = 0
  for (const entry of entries) {
    if (names.has(entry.name.toLowerCase())) continue
    const fresh: WatchEntity & { links?: unknown } = { ...entry, id: current.nextWatchId++ }
    delete fresh.links // a sample register keeps no item links
    current.watch = [...current.watch, fresh]
    restored += 1
  }
  return json({ ...register(), restored })
}

/** A believable review of the sample register: one quiet name, one missing company, a tidier group. */
function sampleReview(): WatchReview {
  const current = mockState()
  const active = current.watch.filter((entity) => entity.status === 'active')
  const quiet = [...active].sort((a, b) => (a.last_hit_at ?? '').localeCompare(b.last_hit_at ?? ''))[0]
  const surgical = active.find((entity) => entity.category === 'Surgical robotics')
  const known = new Set(current.watch.map((entity) => entity.name.toLowerCase()))
  const review: WatchReview = {
    mode: 'ai',
    summary: 'One name has gone quiet, one company keeps appearing without being on your list, and two groups cover nearly the same ground.',
    pause: quiet ? [{ id: quiet.id, name: quiet.name, category: quiet.category || 'Other', reason: 'Nothing new about it for six weeks, and you have not opened its items.' }] : [],
    remove: [],
    add: known.has('sample imaging co')
      ? []
      : [{ name: 'Sample Imaging Co', kind: 'company', category: 'Medical imaging', why: 'Named in five relevant items this month, with a product close to yours.', query: '"Sample Imaging Co"' }],
    regroup: surgical && active.some((entity) => entity.category === 'Medical imaging')
      ? [{ id: surgical.id, name: surgical.name, from: 'Surgical robotics', to: 'Medical imaging', reason: 'Its news is mostly about imaging-guided procedures.' }]
      : [],
    merge_groups: [],
  }
  return review
}

/** Routes under /watch for groups and review; null when the request is not one of them. */
export async function watchManageRoute(method: string, parts: string[], body: Record<string, unknown>, signal?: AbortSignal | null): Promise<Response | null> {
  if (method === 'PATCH' && parts[1] === 'groups' && parts.length === 2) return groupRoute(body as unknown as WatchGroupBody)
  if (method === 'POST' && parts[1] === 'groups' && parts[2] === 'restore') {
    return restoreRoute((body.entries as (WatchEntity & { links?: unknown })[]) ?? [])
  }
  if (method === 'POST' && parts[1] === 'review' && parts.length === 2) {
    await wait(REVIEW_MS, signal)
    return json(sampleReview())
  }
  if (method === 'POST' && parts[1] === 'review' && parts[2] === 'apply') return applyRoute(body as unknown as WatchApplyBody)
  return null
}

/** POST /watch/review/apply: do exactly what was ticked. */
function applyRoute(body: WatchApplyBody): Response {
  const current = mockState()
  const applied = { paused: 0, removed: 0, added: 0, regrouped: 0, merged: 0 }
  const removed = current.watch.filter((entity) => body.remove.includes(entity.id)).map((entity) => ({ ...entity, links: [] }))
  current.watch = current.watch.filter((entity) => !body.remove.includes(entity.id))
  applied.removed = removed.length
  current.watch = current.watch.map((entity) => {
    if (body.pause.includes(entity.id) && entity.status === 'active') {
      applied.paused += 1
      return { ...entity, status: 'muted' as const }
    }
    return entity
  })
  for (const change of body.regroup) {
    const to = storedName(change.to)
    if (to === null) return json({ detail: 'A group name must be one line of up to 60 characters.' }, 422)
    current.watch = current.watch.map((entity) => {
      if (entity.id !== change.id) return entity
      applied.regrouped += 1
      return { ...entity, category: to }
    })
  }
  for (const merge of body.merge_groups) {
    const to = storedName(merge.to)
    if (to === null) return json({ detail: 'A group name must be one line of up to 60 characters.' }, 422)
    current.watch = current.watch.map((entity) => {
      if (!inGroup(entity, merge.from)) return entity
      applied.merged += 1
      return { ...entity, category: to }
    })
  }
  const names = new Set(current.watch.map((entity) => entity.name.toLowerCase()))
  for (const add of body.add) {
    if (names.has(add.name.toLowerCase())) continue
    current.watch = [
      ...current.watch,
      {
        id: current.nextWatchId++, name: add.name, kind: add.kind, category: storedName(add.category) ?? '', topic: null, aliases: [],
        query: add.query || `"${add.name}"`, website: null, status: 'active', why: add.why || null, added_via: 'discovered', last_hit_at: null,
      },
    ]
    applied.added += 1
  }
  return json({ ...register(), applied, removed })
}
