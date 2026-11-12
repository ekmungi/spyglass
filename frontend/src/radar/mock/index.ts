// Sample mode: a fetch replacement that answers every /api/radar endpoint from fixtures, with
// short delays so loading states show. Enabled by ?mock=1 or VITE_RADAR_MOCK=1.
import type { AssistAction, Engine, ItemDetail, Profile, RadarItem, SendMessageBody, WatchEntity, WatchPatchBody } from '../api/types'
import { answerFor, sseStream } from './answers'
import { buildBrief, localDay } from './brief'
import { buildPapers, buildStatus, buildTodayStatus, ENGINES, EXAMPLES, groupWatch, PROFILE, SOURCES } from './catalog'
import { keyPointsFor, readerFor } from './readers'
import { claudeRoute, privacyRoute, projectsRoute, resetClaudeMock } from './claude'
import { filingRoute, resetFilingMock } from './filing'
import { filingSummaryMock } from './filingRun'
import { feedTurn, isFeedThread, itemsByIds, relatedToItem, relatedToText, rememberRetrieved, resetFeedMock, retrievedOf } from './feedAssist'
import { savedView } from './feedViews'
import { importRoute, resetImportMock } from './importer'
import { suggestRoute, tracksRoute } from './tracks'
import { watchManageRoute } from './watchManage'
import { usageRoute } from './usage'
import { addCapturedItem, addMessage, messagesOf, mockState, patchItemState, resetMockState as resetStore, threadFor } from './store'


const PENDING_ID = 105 // first open shows the "preparing" skeleton for a moment
const FAILED_ID = 124 // shows the failed state until Retry
const PENDING_MS = 2500

let engines: Engine[] = ENGINES
let profile: Profile = PROFILE
const COLLECT_MS = 2500

/** Reset every piece of sample state (tests, and a fresh visit to sample mode). */
export function resetMockState(): void {
  resetStore()
  resetImportMock()
  resetClaudeMock()
  resetFilingMock()
  resetFeedMock()
  engines = ENGINES
  profile = PROFILE
}

/** Wait `ms`, rejecting with an AbortError if the signal fires first. */
function delay(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    })
  })
}

/** A JSON Response with the given status. */
function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

const notFound = () => json({ detail: 'Not found' }, 404)

/** Feed filtering, cursor paging and search over the sample items. */
function feed(params: URLSearchParams): Response {
  const tier = params.get('tier')
  const q = (params.get('q') ?? '').toLowerCase().trim()
  const before = params.get('before')
  const limit = Number(params.get('limit') ?? 50) || 50
  // Missed and one Watch group's week bring their own pool (and Missed its own order and a single page).
  const view = savedView(mockState(), params)
  const matches = (view?.items ?? mockState().items.filter((item) => (tier === 'all' ? true : tier ? item.tier === tier : item.tier !== 'out')))
    .filter((item) => !params.get('section') || item.section === params.get('section'))
    .filter((item) => !params.get('kind') || item.kind === params.get('kind'))
    .filter((item) => params.get('saved') !== 'true' || item.state.saved)
    .filter((item) => params.get('from_user') !== 'true' || item.state.from_user)
    .filter((item) => params.get('filed') !== 'true' || Boolean(item.filed))
    .filter((item) => params.get('filing') !== 'waiting' || item.filing === 'waiting')
    .filter((item) => !q || `${item.headline} ${item.why ?? ''} ${item.origin}`.toLowerCase().includes(q))
    .sort((a, b) => (view?.byScore ? 0 : (b.published_at ?? '').localeCompare(a.published_at ?? '')))
  const afterCursor = before && !view?.byScore ? matches.filter((item) => (item.published_at ?? '') < before) : matches
  const page = afterCursor.slice(0, limit)
  const more = afterCursor.length > page.length && !view?.byScore
  return json({ items: page, next_before: more ? page[page.length - 1]?.published_at ?? null : null, total: matches.length })
}

/** The item detail, including the simulated pending and failed reader states. */
function detail(id: number): Response {
  const current = mockState()
  const item = current.items.find((entry) => entry.id === id)
  if (!item) return notFound()
  let reader = item.has_reader || item.source !== 'capture' ? readerFor(item) : null
  if (reader && id === PENDING_ID) {
    const first = current.readerFirstSeen.get(id) ?? Date.now()
    current.readerFirstSeen.set(id, first)
    if (Date.now() - first < PENDING_MS) reader = { ...reader, status: 'pending', html: '' }
  }
  if (reader && id === FAILED_ID && !current.readerRepaired.has(id)) {
    reader = { ...reader, status: 'failed', html: '', error: 'The site refused automated reading (HTTP 403).' }
  }
  const related = current.items.filter((other) => other.section === item.section && other.id !== id && other.tier !== 'out').slice(0, 4)
  const body: ItemDetail = {
    ...item,
    key_points: keyPointsFor(item),
    summary: item.why,
    reader,
    related,
    story_sources: id === 101 ? [{ item_id: 107, name: 'Open Weights Weekly', url: 'https://example.org/1' }, { item_id: 110, name: 'Policy & Compute', url: 'https://example.org/2' }] : [],
    threads: current.threads.filter((thread) => thread.item_id === id).map(({ id: tid, title, updated_at }) => ({ id: tid, title, updated_at })),
  }
  return json(body)
}

/** Start an assistant answer: store both turns and return the SSE stream. */
function sendMessage(threadId: number, body: SendMessageBody, signal?: AbortSignal | null): Response {
  addMessage({ role: 'user', content: body.content, selection: body.selection ?? null, action: body.action ?? null, engine: body.engine ?? null, model: body.model ?? null, error: null }, threadId)
  // The conversation about the feed answers from the items closest to the question, citing them as [#id].
  const feedAnswer = isFeedThread(mockState().threads.find((thread) => thread.id === threadId)) ? feedTurn(body) : null
  if (feedAnswer) rememberRetrieved(threadId, feedAnswer.retrieved)
  const text = feedAnswer?.text ?? answerFor(body.action as AssistAction | undefined, body.content)
  const fails = /\bfail\b/i.test(body.content)
  const reply = fails
    ? null
    : addMessage({ role: 'assistant', content: text, selection: null, action: body.action ?? null, engine: body.engine ?? null, model: body.model ?? null, error: null }, threadId)
  const stream = sseStream(text, reply?.id ?? 0, signal, fails ? 'The engine stopped responding (sample error).' : undefined, feedAnswer?.retrieved)
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

/** The watch register: list, discover, add, edit (including accept and dismiss) and remove. */
async function watchRoute(method: string, parts: string[], body: Record<string, unknown>, signal?: AbortSignal | null): Promise<Response | null> {
  const current = mockState()
  const id = Number(parts[1])
  if (method === 'GET' && parts.length === 1) return json(groupWatch(current.watch, current.items))
  const managed = await watchManageRoute(method, parts, body, signal)
  if (managed) return managed
  if (method === 'POST' && parts[1] === 'discover') {
    await delay(1200, signal)
    const topic = String(body.topic ?? 'your topic')
    const found: WatchEntity = {
      id: current.nextWatchId++,
      name: `Sample company for ${topic}`,
      kind: 'company',
      category: topic,
      topic,
      aliases: [],
      query: `"Sample company for ${topic}"`,
      website: null,
      status: 'suggested',
      why: `Mentioned in recent items about ${topic}.`,
      added_via: 'discovered',
      last_hit_at: null,
    }
    const known = current.watch.some((entity) => entity.name === found.name)
    if (!known) current.watch = [...current.watch, found]
    return json({ suggested: known ? [] : [found], rejected: 0, already_known: known ? 1 : 0 })
  }
  if (method === 'POST' && parts.length === 1) {
    const created: WatchEntity = {
      id: current.nextWatchId++,
      name: String(body.name ?? 'Entity'),
      kind: String(body.kind ?? 'company'),
      category: String(body.category ?? ''),
      topic: null,
      aliases: [],
      query: typeof body.query === 'string' ? body.query : null,
      website: null,
      status: 'active',
      why: null,
      added_via: 'user',
      last_hit_at: null,
    }
    current.watch = [...current.watch, created]
    return json(created)
  }
  const target = current.watch.find((entity) => entity.id === id)
  if (!target) return notFound()
  if (method === 'PATCH') {
    const patch = body as WatchPatchBody
    const updated: WatchEntity = { ...target, ...patch }
    current.watch = current.watch.map((entity) => (entity.id === id ? updated : entity))
    return json(updated)
  }
  if (method === 'DELETE') {
    current.watch = current.watch.filter((entity) => entity.id !== id)
    return new Response(null, { status: 204 })
  }
  return null
}

/** Route one sample request; returns null when no route matches. */
async function route(method: string, path: string, params: URLSearchParams, body: Record<string, unknown>, signal?: AbortSignal | null, form: FormData | null = null): Promise<Response | null> {
  const parts = path.split('/').filter(Boolean)
  const id = Number(parts[1])
  const today = localDay(0)
  const current = mockState()

  if (method === 'GET' && path === '/feed') return feed(params)
  if (method === 'GET' && path === '/feed/related') {
    const text = (params.get('text') ?? '').trim()
    const itemId = Number(params.get('item_id'))
    if (Boolean(text) === Boolean(params.get('item_id'))) return json({ detail: 'Give either text or item_id, not both.' }, 422)
    if (text) return json({ items: relatedToText(text), query: { text } })
    const own = current.items.find((item) => item.id === itemId)
    return own ? json({ items: relatedToItem(itemId), query: { item_id: itemId, headline: own.headline } }) : notFound()
  }
  if (method === 'GET' && path === '/feed/items') {
    const ids = (params.get('ids') ?? '').split(',').map(Number).filter((value) => Number.isInteger(value) && value > 0)
    return ids.length ? json({ items: itemsByIds(ids) }) : json({ detail: 'Give between 1 and 50 item ids.' }, 422)
  }
  if (parts[0] === 'items' && parts.length === 2 && method === 'GET') return detail(id)
  if (parts[0] === 'items' && parts[2] === 'reader' && parts[3] === 'refresh') {
    await delay(900, signal)
    current.readerRepaired.add(id)
    return detail(id)
  }
  if (parts[0] === 'items' && parts[2] === 'signal') {
    if (body.kind === 'open') patchItemState(id, { opened: true })
    return new Response(null, { status: 204 })
  }
  if (parts[0] === 'items' && parts[2] === 'save') {
    const updated = patchItemState(id, { saved: method === 'POST' })
    return updated ? json(updated.state) : notFound()
  }
  if (parts[0] === 'items' && parts[2] === 'vote') {
    const updated = patchItemState(id, { vote: (body.vote as RadarItem['state']['vote']) ?? null })
    return updated ? json(updated.state) : notFound()
  }
  if (method === 'GET' && path === '/today') {
    const days = current.briefExists ? [0, 1, 2, 3, 4].map(localDay) : []
    // Two earlier briefs are unopened, so the line about missed briefs can be seen in sample mode.
    return json({ brief: current.briefExists ? buildBrief(current.items, today) : null, days, unopened_days: current.briefExists ? [days[1], days[3]] : [], status: buildTodayStatus(today, current.briefExists), filing: filingSummaryMock(current.items) })
  }
  if (method === 'GET' && parts[0] === 'briefs') {
    const day = decodeURIComponent(parts[1] ?? '')
    if (!current.briefExists && day === today) return notFound()
    return json(buildBrief(current.items, day, day !== today))
  }
  if (method === 'POST' && path === '/briefs/generate') {
    await delay(2200, signal)
    current.briefExists = true
    return json(buildBrief(current.items, today))
  }
  if (method === 'GET' && path === '/engines') return json(engines)
  if (method === 'PUT' && parts[0] === 'engines') {
    engines = engines.map((engine) => (engine.id === parts[1] ? { ...engine, ...(body as Partial<Engine>), available: true, reason: null } : engine))
    return json(engines.find((engine) => engine.id === parts[1]) ?? null)
  }
  if (method === 'POST' && path === '/threads') {
    const thread = threadFor(body.item_id as number | undefined, body.brief_day as string | undefined, body.new === true)
    return json({ thread, messages: messagesOf(thread.id), ...(isFeedThread(thread) ? { retrieved: retrievedOf(thread.id) } : {}) })
  }
  if (method === 'GET' && parts[0] === 'threads' && parts.length === 2) {
    const thread = current.threads.find((entry) => entry.id === id)
    return thread ? json({ thread, messages: messagesOf(id), ...(isFeedThread(thread) ? { retrieved: retrievedOf(id) } : {}) }) : notFound()
  }
  if (method === 'POST' && parts[0] === 'threads' && parts[2] === 'messages') return sendMessage(id, body as unknown as SendMessageBody, signal)
  if (path === '/profile') {
    if (method === 'PUT') profile = { ...(body as unknown as Profile), version: profile.version + 1 }
    return json({ profile, examples: EXAMPLES })
  }
  if (method === 'GET' && path === '/sources') return json(SOURCES)
  if (method === 'POST' && path === '/capture') {
    const url = String(body.url ?? '')
    if (!/^https?:\/\//i.test(url)) return json({ detail: 'Enter a full web address starting with http:// or https://.' }, 422)
    return json(addCapturedItem(url, body.note as string | undefined))
  }
  if (method === 'POST' && path === '/collect') {
    // Like the service: answer at once, keep working in the background, refuse a second run.
    if (Date.now() < current.collectUntil) return json({ detail: 'a collection is already running' }, 409)
    current.collectUntil = Date.now() + COLLECT_MS
    current.collectedAt = null
    return json({ started: true })
  }
  if (method === 'GET' && path === '/status') {
    const running = Date.now() < current.collectUntil
    if (!running && current.collectUntil > 0 && !current.collectedAt) current.collectedAt = new Date().toISOString()
    return json(buildStatus({ running, lastCollectAt: current.collectedAt ?? undefined }))
  }
  if ((parts[0] === 'items' && parts[2] === 'file') || parts[0] === 'filing') return filingRoute(method, parts, id, body)
  if (parts[0] === 'items' && parts[2] === 'claude') return claudeRoute(method, id, parts[3] ?? '', body)
  if (parts[0] === 'projects') return projectsRoute(method, body)
  if (method === 'GET' && path === '/privacy/outbound') {
    const topics = profile.topics.map((topic) => `- ${topic.name}`).join('\n')
    return privacyRoute(`${profile.statement}\n\nTopics:\n${topics}\n\nLeave out: ${profile.avoid.join(', ')}`, EXAMPLES.liked, EXAMPLES.disliked)
  }
  if (parts[0] === 'usage') return usageRoute(method, parts, params)
  if (parts[0] === 'watch') return watchRoute(method, parts, body, signal)
  if (method === 'POST' && ((parts[0] === 'items' && parts[2] === 'track' && parts[3] === 'suggest') || path === '/track/suggest')) {
    return suggestRoute(parts, body, signal)
  }
  if (parts[0] === 'tracks') return tracksRoute(method, parts, body, signal)
  if (parts[0] === 'import') return importRoute(method, parts, body, form)
  if (method === 'POST' && path === '/papers/search') {
    await delay(1400, signal)
    return json({ papers: buildPapers(String(body.topic ?? ''), Number(body.limit ?? 8)) })
  }
  return null
}

/** The sample-mode fetch: same signature as fetch for URLs under /api/radar. */
export async function mockFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const parsed = new URL(url, 'http://sample.local')
  const path = parsed.pathname.replace(/^\/api\/radar/, '') || '/'
  const method = (init.method ?? 'GET').toUpperCase()
  let body: Record<string, unknown> = {}
  if (typeof init.body === 'string' && init.body) {
    try {
      body = JSON.parse(init.body) as Record<string, unknown>
    } catch {
      return json({ detail: 'Malformed JSON body' }, 400)
    }
  }
  await delay(140 + Math.floor(Math.random() * 160), init.signal)
  const form = init.body instanceof FormData ? init.body : null
  const response = await route(method, path, parsed.searchParams, body, init.signal, form)
  return response ?? notFound()
}
