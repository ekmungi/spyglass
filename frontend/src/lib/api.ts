// Thin fetch wrappers for the service REST API (same origin; /api proxied in dev).
// Highlights API removed; see models.py for the dormant Highlight table.
import type {
  CardJobs,
  ClaudeJob,
  JobKind,
  LinkStatus,
  AddedPage,
  Brief,
  BriefGenerateResult,
  BriefSummary,
  CardData,
  CardPatch,
  CategoryInfo,
  DiscoverResult,
  FeedData,
  Feedback,
  FetchJobState,
  FulltextResult,
  InboxData,
  RecatResult,
  Relevance,
  RunRow,
  ScoredCard,
  SearchResult,
  ServiceSettings,
} from './types'

/**
 * Thrown by addFeed when the service returns 422 {"kind":"not_a_feed",...}.
 * Carries the resolved URL from the response so the caller can open discovery.
 */
export class NotAFeedError extends Error {
  /** The resolved URL the server tried to parse as a feed. */
  readonly url: string

  constructor(url: string) {
    super(`Not a feed: ${url}`)
    this.name = 'NotAFeedError'
    this.url = url
  }
}

/** Thrown by addFeed when the site refused Spyglass or could not be reached. */
export class FeedRefusedError extends Error {
  constructor(reason: string) {
    super(reason)
    this.name = 'FeedRefusedError'
  }
}

/**
 * Thrown by openClaude when the service could not open the Claude desktop app (502).
 * Carries the full prompt so the dashboard can offer to copy it instead.
 */
export class ClaudeUnavailableError extends Error {
  /** The prompt the session would have opened with. */
  readonly prompt: string

  constructor(prompt: string) {
    super("Couldn't open the Claude desktop app")
    this.name = 'ClaudeUnavailableError'
    this.prompt = prompt
  }
}

// Shared JSON headers for the methods that send a body.
const JSON_HEADERS = { 'Content-Type': 'application/json' }

/** Perform a request and parse JSON, throwing a readable error on failure.
 * 204 responses (deletes) resolve to undefined instead of parsing a body. */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${url} failed: ${response.status}`)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

/** List cards; the service hides dismissed cards unless asked for them. */
export function getCards(params?: { state?: string; source?: string }): Promise<CardData[]> {
  const query = new URLSearchParams(params as Record<string, string>).toString()
  return request(`/api/cards${query ? `?${query}` : ''}`)
}

/** Apply a partial update (state, note, prompt) to one card. */
export function patchCard(id: number, patch: CardPatch): Promise<CardData> {
  return request(`/api/cards/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Activity rows, newest first. */
export function getRuns(): Promise<RunRow[]> {
  return request('/api/runs')
}

/** Trigger collection; with ifStale, only when data is older than the window. */
export function refresh(ifStale: boolean): Promise<{ refreshed: boolean; sources: number }> {
  return request(`/api/refresh${ifStale ? '?if_stale=true' : ''}`, { method: 'POST' })
}

/** Fetch a finished card's briefing markdown for in-dashboard reading. */
export function getBriefing(id: number): Promise<{ markdown: string }> {
  return request(`/api/cards/${id}/briefing`)
}

/** Open a new Claude desktop session (Code tab) in the vault with the prompt typed in;
 * the service names the selected cards in it. model is sent for older
 * services and ignored: a claude:// link has no model. Throws ClaudeUnavailableError
 * when the desktop app could not be opened. */
export async function openClaude(
  prompt?: string,
  model?: string,
  includeSelection = true,
): Promise<{ opened: boolean }> {
  const response = await fetch('/api/open-claude', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      prompt: prompt ?? null,
      model: model ?? null,
      include_selection: includeSelection,
    }),
  })
  if (response.status === 502) {
    const body = (await response.json().catch(() => ({}))) as { prompt?: string }
    throw new ClaudeUnavailableError(body.prompt ?? prompt ?? '')
  }
  if (!response.ok) {
    throw new Error(`POST /api/open-claude failed: ${response.status}`)
  }
  return (await response.json()) as { opened: boolean }
}

/** Read a card's stored full-text markdown; status 'absent' when none stored. */
export function getFulltext(id: number): Promise<FulltextResult> {
  return request(`/api/cards/${id}/fulltext`)
}

/** Fetch one card in full (incl. the complete summary) for the reader. */
export function getCard(id: number): Promise<CardData> {
  return request(`/api/cards/${id}`)
}

/**
 * Queue a fetch + re-enrich of a card's full text.
 *
 * Returns as soon as the job is recorded (202) — the tiered acquisition ladder runs on
 * the service's background worker, which can take 30-60s on the browser tier. Progress is
 * read back from getFulltext's `job`, never held in component state.
 *
 * The response is the job, NOT an enrichment result: the fresh summary/category must be
 * re-read with getCard once the job completes. This return type is deliberately narrow —
 * declaring the old enrichment-result shape here would hide a backend/frontend drift.
 */
export function fetchFulltext(id: number): Promise<FetchJobState> {
  return request(`/api/cards/${id}/fulltext`, { method: 'POST' })
}

/**
 * Card ids with a queued or running fetch, for the list's pending markers.
 * Its own endpoint so the /api/cards list payload stays lean.
 *
 * The array is validated rather than asserted: a service that predates this endpoint
 * answers with something else entirely, and a cosmetic marker must never be able to take
 * the dashboard down on the strength of an assumed response shape.
 */
export function getActiveFetchJobs(): Promise<number[]> {
  return request<{ card_ids?: number[] }>('/api/fetch-jobs/active').then((body) =>
    Array.isArray(body?.card_ids) ? body.card_ids : [],
  )
}

/** The paper inbox: the channel, the latest run and the shared papers. */
export function getInbox(): Promise<InboxData> {
  return request('/api/inbox')
}

/** Open a run's debrief note in Obsidian. */
export function openRunDebrief(runId: number): Promise<{ opened: boolean }> {
  return request(`/api/inbox/runs/${runId}/open-debrief`, { method: 'POST' })
}

/** Open a filed paper's vault note in Obsidian. */
export function openInboxNote(cardId: number): Promise<{ opened: boolean }> {
  return request(`/api/inbox/${cardId}/open-note`, { method: 'POST' })
}

/** Record the multi-select so a Claude session can pick it up via MCP. */
export function postSelection(
  cardIds: number[],
  openCardId?: number | null,
): Promise<{ card_ids: number[] }> {
  // open_card_id is sent only when given, so "this one" survives a selection-only update.
  const body = openCardId === undefined ? { card_ids: cardIds } : { card_ids: cardIds, open_card_id: openCardId }
  return request('/api/selection', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  })
}

/** Whether a Claude session is linked to Spyglass, since when, and its last call. */
export function getLinkStatus(): Promise<LinkStatus> {
  return request('/api/link')
}

/** Open a new Claude desktop session that links itself to Spyglass. The given items
 * become the selection and are named in its prompt; task follows the link step. Throws
 * ClaudeUnavailableError when the desktop app could not be opened. */
export async function openLinkedSession(
  cardIds?: number[],
  task?: string,
): Promise<{ opened: boolean }> {
  const response = await fetch('/api/link/open', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ card_ids: cardIds ?? null, task: task ?? null }),
  })
  if (response.status === 502) {
    const body = (await response.json().catch(() => ({}))) as { prompt?: string }
    throw new ClaudeUnavailableError(body.prompt ?? task ?? '')
  }
  if (!response.ok) {
    throw new Error(`POST /api/link/open failed: ${response.status}`)
  }
  return (await response.json()) as { opened: boolean }
}

/** Full-text search across stored markdown; results carry a match snippet. */
export function search(q: string): Promise<SearchResult[]> {
  return request(`/api/search?${new URLSearchParams({ q })}`)
}

/** All managed categories with counts; empty ones included. */
export function getCategories(): Promise<CategoryInfo[]> {
  return request('/api/categories')
}

/** Create an empty category; it persists in dropdowns without moving items. */
export function createCategory(name: string): Promise<{ name: string }> {
  return request('/api/categories', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ name }),
  })
}

/** Remove a managed category; its cards re-bucket to Unsorted. */
export function deleteCategory(name: string): Promise<{ deleted: string }> {
  return request(`/api/categories/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

/** Kick the background Recategorize pass; returns started|already_running. */
export function recategorize(): Promise<{ status: string }> {
  return request('/api/recategorize', { method: 'POST' })
}

/** Poll the latest Recategorize run: status + proposed new categories to review. */
export function getRecategorize(): Promise<RecatResult> {
  return request('/api/recategorize')
}

/** Accept a candidate: create the category and file its cluster's cards into it. */
export function acceptCandidate(
  name: string,
  cardIds: number[],
): Promise<{ name: string; assigned: number }> {
  return request('/api/recategorize/accept', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ name, card_ids: cardIds }),
  })
}

/** Current editable service settings. */
export function getSettings(): Promise<ServiceSettings> {
  return request('/api/settings')
}

/** Persist edited service settings; absent fields stay unchanged. */
export function patchSettings(patch: Partial<ServiceSettings>): Promise<ServiceSettings> {
  return request('/api/settings', {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(patch),
  })
}

/** Permanently delete a card by id. */
export function deleteCard(id: number): Promise<{ deleted: number }> {
  return request(`/api/cards/${id}`, { method: 'DELETE' })
}

/** Open a card's URL in the system default browser. */
export function openExternal(id: number): Promise<{ opened: boolean; url: string }> {
  return request(`/api/cards/${id}/open-external`, { method: 'POST' })
}

/** Rename a category everywhere (managed set + cards, override-safe). */
export function renameCategory(oldName: string, name: string): Promise<{ name: string }> {
  return request(`/api/categories/${encodeURIComponent(oldName)}`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify({ name }),
  })
}

/** User relevance override; the service applies the net-change rule.
 * Pass null to clear the override and revert to the AI value. */
export function setCardRelevance(
  id: number,
  relevance: Relevance | null,
): Promise<{ relevance: Relevance | null; relevance_override: boolean }> {
  return request(`/api/cards/${id}/relevance`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify({ relevance }),
  })
}

/** Set or clear a card's thumbs feedback; null clears it. Returns the full updated card. */
export function setCardFeedback(id: number, feedback: Feedback): Promise<CardData> {
  return request(`/api/cards/${id}/feedback`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify({ feedback }),
  })
}

/** User recategorize; override flag follows the net-change rule. */
export function setCardCategory(
  id: number,
  category: string,
): Promise<{ category: string; category_override: boolean }> {
  return request(`/api/cards/${id}/category`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify({ category }),
  })
}

/** Articles most similar to this one, by embedding cosine.
 * Ranked best-first; each result carries a score (0..1). k caps the count. */
export function getSimilar(id: number, k?: number): Promise<ScoredCard[]> {
  return request(`/api/cards/${id}/similar${k !== undefined ? `?k=${k}` : ''}`)
}

/**
 * Add a single web page by URL: the service fetches, enriches, and
 * judges it (can take ~30s), returning the card plus a created/exists status.
 * 400 (invalid URL) throws an honest message; other failures a generic one.
 */
export async function addPage(url: string): Promise<AddedPage> {
  const response = await fetch('/api/pages', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ url }),
  })
  if (!response.ok) {
    if (response.status === 400) {
      throw new Error('That does not look like a valid page URL.')
    }
    throw new Error(`POST /api/pages failed: ${response.status}`)
  }
  return (await response.json()) as AddedPage
}

// --- Feeds API ---

/** List all managed feeds with health and item count. */
export function getFeeds(): Promise<FeedData[]> {
  return request('/api/feeds')
}

/**
 * Add a feed by URL with an optional display name.
 * On success returns FeedData.
 * Throws NotAFeedError when the service returns 422 {"kind":"not_a_feed",...}.
 * Throws a generic Error for any other non-ok response.
 *
 * @param url  - The feed or page URL to add.
 * @param name - Optional display name; omitted when empty or undefined.
 */
export async function addFeed(url: string, name?: string): Promise<FeedData> {
  const body = name ? { url, name } : { url }
  const response = await fetch('/api/feeds', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    if (response.status === 422) {
      // Attempt to parse the not_a_feed discriminator from the FastAPI detail envelope.
      try {
        const errBody = (await response.json()) as {
          detail?: { kind?: string; url?: string; reason?: string }
        }
        if (errBody?.detail?.kind === 'not_a_feed') {
          throw new NotAFeedError(errBody.detail.url ?? url)
        }
        // Blocked or unreachable -- show the service's plain reason.
        if (errBody?.detail?.reason) throw new FeedRefusedError(errBody.detail.reason)
      } catch (err) {
        if (err instanceof NotAFeedError || err instanceof FeedRefusedError) throw err
        // JSON parse failed or unrecognised body — fall through to generic error.
      }
    }
    throw new Error(`POST /api/feeds failed: ${response.status}`)
  }
  if (response.status === 204) return undefined as unknown as FeedData
  return (await response.json()) as FeedData
}

/**
 * Discover feed candidates reachable from a page URL.
 * depth='shallow' checks the page itself; 'deep' follows link-rel hints.
 */
export function discoverFeeds(url: string, depth: 'shallow' | 'deep'): Promise<DiscoverResult> {
  return request('/api/feeds/discover', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ url, depth }),
  })
}

/** Partially update a feed (enabled, name). */
export function patchFeed(
  id: number,
  patch: { enabled?: boolean; name?: string },
): Promise<FeedData> {
  return request(`/api/feeds/${id}`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(patch),
  })
}

/** Delete a feed; returns how many cards were also removed. */
export function deleteFeed(id: number): Promise<{ deleted: boolean; cards_removed: number }> {
  return request(`/api/feeds/${id}`, { method: 'DELETE' })
}

// --- Daily Brief API ---

/**
 * Thrown by generateBrief when the service answers 503 {"detail":{"status":"llm_unavailable"}}.
 * The UI shows the paused message; held items are briefed on the next run.
 */
export class BriefUnavailableError extends Error {
  constructor() {
    super('Brief paused — the LLM is unreachable; items are held for the next run.')
    this.name = 'BriefUnavailableError'
  }
}

/** List brief summaries, newest first (no markdown body). */
export function getBriefs(): Promise<BriefSummary[]> {
  return request('/api/briefs')
}

/** Read one brief including its full markdown body. */
export function getBrief(id: number): Promise<Brief> {
  return request(`/api/briefs/${id}`)
}

/**
 * Generate every due Daily Brief on demand.
 * Resolves to { composed, status, held }: the briefs composed this run (light
 * summaries, newest first), a status ('composed' | 'empty'), and how many due days
 * were held back (a heavy day the composer paused on) so the caller can tell
 * "nothing was due" from "something is stuck".
 * Throws BriefUnavailableError on 503 llm_unavailable; a generic Error otherwise.
 */
export async function generateBrief(): Promise<BriefGenerateResult> {
  const response = await fetch('/api/briefs/generate', { method: 'POST' })
  if (!response.ok) {
    if (response.status === 503) {
      // 503 from this endpoint has exactly one meaning (the compose pause), so a
      // malformed/empty error body must not demote it to a generic failure.
      throw new BriefUnavailableError()
    }
    throw new Error(`POST /api/briefs/generate failed: ${response.status}`)
  }
  return (await response.json()) as BriefGenerateResult
}

/**
 * Recompose an existing brief in place: the service re-runs the
 * composer over the same coverage window and returns the fresh full Brief.
 * Throws BriefUnavailableError on 503 llm_unavailable; a generic Error otherwise.
 */
export async function recomposeBrief(id: number): Promise<Brief> {
  const response = await fetch(`/api/briefs/${id}/recompose`, { method: 'POST' })
  if (!response.ok) {
    if (response.status === 503) {
      // Same single-meaning 503 as generate: the compose pause.
      throw new BriefUnavailableError()
    }
    throw new Error(`POST /api/briefs/${id}/recompose failed: ${response.status}`)
  }
  return (await response.json()) as Brief
}

/** Import feeds from OPML or markdown text (raw body, not JSON). */
export function importFeeds(content: string): Promise<{ added: number; skipped: number }> {
  return request('/api/feeds/import', {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: content,
  })
}

/** Export all feeds as OPML or markdown text; returns the file content as a string. */
export function exportFeeds(format: 'opml' | 'markdown'): Promise<string> {
  return fetch(`/api/feeds/export?format=${format}`).then((r) => {
    if (!r.ok) throw new Error(`GET /api/feeds/export failed: ${r.status}`)
    return r.text()
  })
}

/** A failed request with the service's own explanation (its `detail`), for showing as is. */
export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** POST JSON and parse the answer; a refusal throws ApiError with the service's reason. */
async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body) })
  if (!response.ok) {
    const answer = (await response.json().catch(() => ({}))) as { detail?: unknown }
    const detail = typeof answer.detail === 'string' ? answer.detail : `POST ${url} failed: ${response.status}`
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

/** Queue Prepare detail or File it for one item; an identical job already queued or
 * running is returned instead. */
export function startJob(kind: JobKind, cardId: number): Promise<{ job: ClaudeJob; created: boolean }> {
  return postJson('/api/jobs', { kind, card_id: cardId })
}

/** An item's latest background jobs, newest first, and its note. */
export function getCardJobs(cardId: number): Promise<CardJobs> {
  return request(`/api/cards/${cardId}/jobs`)
}

/** Cancel a queued or running job. */
export function cancelJob(jobId: number): Promise<ClaudeJob> {
  return postJson(`/api/jobs/${jobId}/cancel`, {})
}

/** Move an unfiled detailed note to the vault's .trash; counts as a thumbs down. */
export function deleteDetailNote(cardId: number): Promise<{ trashed: string }> {
  return postJson(`/api/cards/${cardId}/detail-note/delete`, {})
}

/** End the link to the Claude session: its next call to Spyglass is refused. */
export function endLink(): Promise<LinkStatus> {
  return postJson('/api/link/end', {})
}

/** Tell the service this window is closing; the link ends unless a window checks in again soon.
 * A beacon, because a closing page cannot wait for an answer. */
export function sayWindowClosing(): void {
  try {
    navigator.sendBeacon?.('/api/link/window-closed', new Blob(['{}'], { type: 'application/json' }))
  } catch {
    // Nothing to do: the link then stays until it is ended or replaced.
  }
}
