// Typed client: one function per /api/radar endpoint. Every failure is thrown as an ApiError.
import { ApiError, httpError, transportError } from './errors'
import { API_BASE, apiFetch } from './transport'
import type {
  BriefDoc,
  ClaudeOpened,
  ClaudePreview,
  ClaudeRequest,
  FilingAnswer,
  FilingChoice,
  FilingOverview,
  FilingQueue,
  FilingResult,
  ImportButtonKey,
  ImportTextBody,
  StagedImport,
  StageImportBody,
  CaptureBody,
  CollectResult,
  CreateThreadBody,
  Engine,
  EngineUpdate,
  FeedPage,
  FeedQuery,
  ItemDetail,
  PapersResponse,
  PrivacyOutbound,
  Profile,
  ProfileResponse,
  ProjectRow,
  ProjectsBody,
  ProjectsResponse,
  RadarItem,
  RadarStatus,
  RelatedResponse,
  SignalBody,
  SourcesResponse,
  ThreadWithMessages,
  TodayResponse,
  Track,
  TrackCreateBody,
  TrackCreated,
  TrackPatchBody,
  TracksResponse,
  TrackSuggestResponse,
  Vote,
  WatchCreateBody,
  WatchDiscoverResponse,
  WatchEntity,
  WatchApplyBody,
  WatchApplyResponse,
  WatchGroupBody,
  WatchGroupResponse,
  WatchPatchBody,
  WatchResponse,
  WatchRestoreResponse,
  WatchReview,
  RemovedWatchEntity,
} from './types'

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

/** Send one JSON request and parse the JSON reply; 204 and empty bodies resolve to null. */
export async function request<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await apiFetch(path, {
      method,
      signal,
      headers: body === undefined ? { Accept: 'application/json' } : { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (cause) {
    throw transportError(cause, path)
  }
  return readReply<T>(response, path)
}

/** POST a multipart form (a file upload); the browser sets the content type and its boundary. */
export async function requestForm<T>(path: string, form: FormData, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await apiFetch(path, { method: 'POST', signal, headers: { Accept: 'application/json' }, body: form })
  } catch (cause) {
    throw transportError(cause, path)
  }
  return readReply<T>(response, path)
}

/** Parse a reply as JSON (empty is null) and throw an ApiError for any failure status. */
async function readReply<T>(response: Response, path: string): Promise<T> {
  const text = await response.text().catch(() => '')
  let parsed: unknown = null
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      if (response.ok) {
        throw new ApiError('Spyglass sent a reply this page could not read.', { status: response.status, kind: 'parse', path })
      }
      parsed = text
    }
  }
  if (!response.ok) throw httpError(response.status, parsed, path)
  return parsed as T
}

/** Build a query string from defined, non-empty values; booleans become 'true'. */
export function queryString(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '' || value === false) continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

/** Accept a brief either bare or wrapped as {brief: doc}. */
function unwrapBrief(raw: unknown): BriefDoc | null {
  if (!raw || typeof raw !== 'object') return null
  if ('sections' in raw) return raw as BriefDoc
  if ('brief' in raw) return (raw as { brief: BriefDoc | null }).brief
  return null
}

/** Accept a thread reply either as {thread, messages} or as a bare thread object. */
function unwrapThread(raw: unknown): ThreadWithMessages {
  if (raw && typeof raw === 'object' && 'thread' in raw) {
    const value = raw as Partial<ThreadWithMessages>
    return { thread: value.thread as ThreadWithMessages['thread'], messages: value.messages ?? [], ...(value.retrieved ? { retrieved: value.retrieved } : {}) }
  }
  return { thread: raw as ThreadWithMessages['thread'], messages: [] }
}

/** Keep only the non-empty strings of a list (learned example titles). */
const titles = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string' && entry.trim().length > 0) : []

/**
 * Read a GET or PUT /profile reply. The service answers {profile, examples}; a bare profile
 * document is accepted too, and any missing part becomes empty rather than undefined.
 */
export function parseProfileReply(raw: unknown): ProfileResponse {
  const wrapped = raw && typeof raw === 'object' && 'profile' in raw
  const body = (wrapped ? raw : { profile: raw }) as { profile: Partial<Profile> | null; examples?: { liked?: unknown; disliked?: unknown } }
  const doc = body.profile ?? {}
  return {
    profile: {
      ...doc,
      version: typeof doc.version === 'number' ? doc.version : 0,
      statement: typeof doc.statement === 'string' ? doc.statement : '',
      sections: Array.isArray(doc.sections) ? doc.sections : [],
      topics: Array.isArray(doc.topics) ? doc.topics : [],
      avoid: Array.isArray(doc.avoid) ? doc.avoid : [],
    },
    examples: { liked: titles(body.examples?.liked), disliked: titles(body.examples?.disliked) },
  }
}

/* ---------- items ---------- */

export const getFeed = (query: FeedQuery, signal?: AbortSignal) =>
  request<FeedPage>('GET', `/feed${queryString({ ...query })}`, undefined, signal)
/** Feed items close to a text or to an item (exactly one of the two), closest first. */
export const getRelated = (query: { text?: string; item_id?: number }, signal?: AbortSignal) =>
  request<RelatedResponse>('GET', `/feed/related${queryString({ ...query, limit: 40 })}`, undefined, signal)
/** The feed items with these ids, in the order given (unknown ids are left out). */
export const getFeedItems = (ids: number[], signal?: AbortSignal) =>
  request<{ items: RadarItem[] }>('GET', `/feed/items${queryString({ ids: ids.join(',') })}`, undefined, signal)
export const getItem = (id: number, signal?: AbortSignal) => request<ItemDetail>('GET', `/items/${id}`, undefined, signal)
export const refreshReader = (id: number) => request<unknown>('POST', `/items/${id}/reader/refresh`, {})
/** Same-origin URL of an item's PDF, for the built-in viewer. */
export const itemPdfUrl = (id: number) => `${API_BASE}/items/${id}/pdf`
export const sendSignal = (id: number, body: SignalBody) => request<unknown>('POST', `/items/${id}/signal`, body)
export const saveItem = (id: number) => request<unknown>('POST', `/items/${id}/save`, {})
export const unsaveItem = (id: number) => request<unknown>('DELETE', `/items/${id}/save`)
export const voteItem = (id: number, vote: Vote) => request<unknown>('POST', `/items/${id}/vote`, { vote })

/* ---------- briefs ---------- */

export const getToday = (signal?: AbortSignal) => request<TodayResponse>('GET', '/today', undefined, signal)
export const getBrief = async (day: string, signal?: AbortSignal) =>
  unwrapBrief(await request<unknown>('GET', `/briefs/${encodeURIComponent(day)}`, undefined, signal))
export const generateBrief = async (day: string | null = null) =>
  unwrapBrief(await request<unknown>('POST', '/briefs/generate', { day }))

/* ---------- assistant ---------- */

export const getEngines = async (signal?: AbortSignal): Promise<Engine[]> => {
  const raw = await request<unknown>('GET', '/engines', undefined, signal)
  if (Array.isArray(raw)) return raw as Engine[]
  return ((raw as { engines?: Engine[] } | null)?.engines ?? []) as Engine[]
}
export const updateEngine = (id: string, body: EngineUpdate) => request<Engine>('PUT', `/engines/${encodeURIComponent(id)}`, body)
export const createThread = async (body: CreateThreadBody) => unwrapThread(await request<unknown>('POST', '/threads', body))
export const getThread = async (id: number, signal?: AbortSignal) =>
  unwrapThread(await request<unknown>('GET', `/threads/${id}`, undefined, signal))

/* ---------- To file queue ---------- */

/** Put an item in the To file queue (or change its choices); nothing is opened or written. */
export const queueForFiling = (id: number, choice: FilingChoice = {}) => request<FilingResult>('POST', `/items/${id}/file`, choice)
/** Take an item out of the To file queue. */
export const unqueueFiling = (id: number) => request<FilingResult>('DELETE', `/items/${id}/file`)
/** Every waiting item with the reader's choices, oldest first. */
export const getFilingQueue = (signal?: AbortSignal) => request<FilingQueue>('GET', '/filing', undefined, signal)
/** The request that would be sent to Claude Code for the whole queue; nothing is opened. */
export const previewFiling = (signal?: AbortSignal) => request<ClaudePreview>('POST', '/filing/preview', {}, signal)
/** Open ONE Claude Code session in the vault to file the whole queue. */
export const openFiling = () => request<ClaudeOpened>('POST', '/filing/open', {})
/** The queue plus the background run's status, open questions, plan and recent filings. */
export const getFilingOverview = (signal?: AbortSignal) => request<FilingOverview>('GET', '/filing', undefined, signal)
/** Every answered question of one Submit; the next background run applies them. */
export const submitFilingAnswers = (answers: FilingAnswer[]) => request<{ answered: number }>('POST', '/filing/answers', { answers })
/** One Approve for the plan: approved rows are filed by the next run, struck rows leave the queue. */
export const approveFilingPlan = (approved: number[], struck: number[]) =>
  request<{ approved: number; struck: number }>('POST', '/filing/plan/approve', { approved, struck })
/** Open the note an item was filed as, in Obsidian. */
export const openFiledNote = (id: number) => request<{ opened: boolean }>('POST', `/filing/recent/${id}/open`, {})

/* ---------- profile ---------- */

export const getProfile = async (signal?: AbortSignal) => parseProfileReply(await request<unknown>('GET', '/profile', undefined, signal))
export const putProfile = async (profile: Profile) => parseProfileReply(await request<unknown>('PUT', '/profile', profile))

/* ---------- sources ---------- */

export const getSources = (signal?: AbortSignal) => request<SourcesResponse>('GET', '/sources', undefined, signal)
export const captureLink = (body: CaptureBody) => request<RadarItem>('POST', '/capture', body)
export const collectNow = () => request<CollectResult>('POST', '/collect', {})
export const getStatus = (signal?: AbortSignal) => request<RadarStatus>('GET', '/status', undefined, signal)

/* ---------- watch ---------- */

export const getWatch = (signal?: AbortSignal) => request<WatchResponse>('GET', '/watch', undefined, signal)
export const discoverWatch = (topic: string) => request<WatchDiscoverResponse>('POST', '/watch/discover', { topic })
export const createWatch = (body: WatchCreateBody) => request<WatchEntity>('POST', '/watch', body)
export const patchWatch = (id: number, body: WatchPatchBody) => request<WatchEntity>('PATCH', `/watch/${id}`, body)
export const deleteWatch = (id: number) => request<unknown>('DELETE', `/watch/${id}`)
export const patchWatchGroup = (body: WatchGroupBody) => request<WatchGroupResponse>('PATCH', '/watch/groups', body)
export const restoreWatchGroup = (entries: RemovedWatchEntity[]) => request<WatchRestoreResponse>('POST', '/watch/groups/restore', { entries })
export const reviewWatch = (signal?: AbortSignal) => request<WatchReview>('POST', '/watch/review', {}, signal)
export const applyWatchReview = (body: WatchApplyBody) => request<WatchApplyResponse>('POST', '/watch/review/apply', body)

/* ---------- papers ---------- */

export const searchPapers = (topic: string, limit = 8) => request<PapersResponse>('POST', '/papers/search', { topic, limit })

/* ---------- tracks (follow more like this) ---------- */

/** Ask for follow suggestions read from one item; the service takes 10 to 30 seconds. */
export const suggestTracksForItem = (id: number, signal?: AbortSignal) =>
  request<TrackSuggestResponse>('POST', `/items/${id}/track/suggest`, {}, signal)
/** The same for a web address; the reply also carries the item the address became. */
export const suggestTracksForUrl = (url: string, signal?: AbortSignal) =>
  request<TrackSuggestResponse>('POST', '/track/suggest', { url }, signal)
export const getTracks = async (signal?: AbortSignal): Promise<Track[]> =>
  (await request<TracksResponse>('GET', '/tracks', undefined, signal)).tracks ?? []
export const createTrack = (body: TrackCreateBody) => request<TrackCreated>('POST', '/tracks', body)
export const patchTrack = (id: number, body: TrackPatchBody) => request<Track>('PATCH', `/tracks/${id}`, body)
export const deleteTrack = (id: number) => request<unknown>('DELETE', `/tracks/${id}`)

/* ---------- Open in Claude Code ---------- */

/** What would be sent to Claude Code for this item and choice; nothing is opened. */
export const previewClaude = (id: number, body: ClaudeRequest, signal?: AbortSignal) =>
  request<ClaudePreview>('POST', `/items/${id}/claude/preview`, body, signal)
/** Open the reader's own Claude Code in their vault with this item; the body is what previewClaude showed. */
export const openInClaude = (id: number, body: ClaudeRequest) => request<ClaudeOpened>('POST', `/items/${id}/claude/open`, body)

/* ---------- projects the assistant may mention ---------- */

/** The reader's vault projects with the one line the AI may see for each. */
export const getProjects = async (signal?: AbortSignal): Promise<ProjectRow[]> =>
  (await request<ProjectsResponse | null>('GET', '/projects', undefined, signal))?.projects ?? []
/** Save the descriptions; projects not listed (or with an empty line) stay private. */
export const putProjects = async (body: ProjectsBody): Promise<ProjectRow[]> =>
  (await request<ProjectsResponse | null>('PUT', '/projects', body))?.projects ?? []

/* ---------- privacy ---------- */

/** What Spyglass sends out right now, to whom, and the four privacy switches. */
export const getPrivacyOutbound = (signal?: AbortSignal) => request<PrivacyOutbound>('GET', '/privacy/outbound', undefined, signal)

/* ---------- import (bring in a page the reader has open in the browser) ---------- */

const stagedPath = (token: string) => `/import/staged/${encodeURIComponent(token)}`
/** Park a page received from the Send to Spyglass button; nothing is added until it is accepted. */
export const stageImport = (body: StageImportBody) => request<{ token: string }>('POST', '/import/stage', body)
export const getStagedImport = (token: string, signal?: AbortSignal) => request<StagedImport>('GET', stagedPath(token), undefined, signal)
export const acceptStagedImport = (token: string) => request<RadarItem>('POST', `${stagedPath(token)}/accept`, {})
export const discardStagedImport = (token: string) => request<unknown>('DELETE', stagedPath(token))
/** The secret the bookmark button carries (this site only). */
export const getImportButtonKey = (signal?: AbortSignal) => request<ImportButtonKey>('GET', '/import/button-key', undefined, signal)
/** Make a new secret; buttons built with the old one stop working. */
export const rotateImportButtonKey = () => request<ImportButtonKey>('POST', '/import/button-key/rotate', {})
export const importText = (body: ImportTextBody) => request<RadarItem>('POST', '/import/text', body)
/** Add a saved .pdf, .html or .mhtml file as the readable copy of an address. */
export const importFile = (url: string, file: File) => {
  const form = new FormData()
  form.set('url', url)
  form.set('file', file, file.name)
  return requestForm<RadarItem>('/import/file', form)
}
