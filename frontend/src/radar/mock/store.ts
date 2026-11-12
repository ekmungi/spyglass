// Sample-mode state: the in-memory copy of items, threads and messages that mock requests read
// and change, so saves, votes and conversations persist while the page stays open.
import type { AssistMessage, ItemState, RadarItem, Thread, Track, WatchEntity } from '../api/types'
import { seedWatch } from './catalog'
import { buildItems } from './items'
import { seedTracks } from './trackData'

interface MockState {
  items: RadarItem[]
  threads: Thread[]
  messages: { threadId: number; message: AssistMessage }[]
  briefExists: boolean
  readerFirstSeen: Map<number, number>
  readerRepaired: Set<number>
  nextMessageId: number
  nextItemId: number
  /** The watch register as a flat list; accept, dismiss, add, edit and remove change it. */
  watch: WatchEntity[]
  nextWatchId: number
  /** The followed topics; following, editing and stopping change it. */
  tracks: Track[]
  nextTrackId: number
  /** Epoch ms until which a sample collection counts as running (0 when none is). */
  collectUntil: number
  /** When the last sample collection finished, or null before any. */
  collectedAt: string | null
}

let state: MockState | null = null

/** True when the URL asks sample mode to start without a brief (?brief=none). */
function startsEmpty(): boolean {
  if (typeof window === 'undefined') return false
  const query = `${window.location.search}&${window.location.hash.split('?')[1] ?? ''}`
  return /(^|[?&])brief=none(&|$)/.test(query)
}

/** The live sample state, created on first use. */
export function mockState(): MockState {
  if (!state) {
    // One item sent in over Slack starts out already filed, so that state can be seen without opening Claude Code.
    const items = buildItems().map((item) =>
      item.state.captured_via === 'slack'
        ? { ...item, filed: { path: 'Regulation notes/Resources/Post-market surveillance talk.md', project: 'Regulation notes', at: new Date(Date.now() - 86_400_000).toISOString() } }
        : item,
    )
    state = {
      items,
      threads: [],
      messages: [],
      briefExists: !startsEmpty(),
      readerFirstSeen: new Map(),
      readerRepaired: new Set(),
      nextMessageId: 1,
      nextItemId: 141,
      watch: seedWatch(),
      nextWatchId: 100,
      tracks: seedTracks(items),
      nextTrackId: 10,
      collectUntil: 0,
      collectedAt: null,
    }
  }
  return state
}

/** Reset the sample state (tests). */
export function resetMockState(): void {
  state = null
}

/** Replace one item's state with a patched copy. Returns the updated item or null. */
export function patchItemState(id: number, patch: Partial<ItemState>): RadarItem | null {
  const current = mockState()
  const found = current.items.find((item) => item.id === id)
  if (!found) return null
  const updated = { ...found, state: { ...found.state, ...patch } }
  current.items = current.items.map((item) => (item.id === id ? updated : item))
  return updated
}

/** Replace fields of one item (outside its `state`) with a patched copy. Returns the updated item or null. */
export function patchItem(id: number, patch: Partial<RadarItem>): RadarItem | null {
  const current = mockState()
  const found = current.items.find((item) => item.id === id)
  if (!found) return null
  const updated = { ...found, ...patch }
  current.items = current.items.map((item) => (item.id === id ? updated : item))
  return updated
}

/** Add a captured link as a new from-you item at the top of the feed. */
export function addCapturedItem(url: string, note: string | undefined): RadarItem {
  const current = mockState()
  const id = current.nextItemId++
  let host = 'Link you sent'
  try {
    host = new URL(url).hostname.replace(/^www\./, '')
  } catch {
    /* keep the generic label for an unparseable URL */
  }
  const item: RadarItem = {
    id,
    title: note?.trim() || `Saved link from ${host}`,
    headline: note?.trim() || `Saved link from ${host}`,
    url,
    source: 'capture',
    origin: host,
    published_at: new Date().toISOString(),
    fetched_at: new Date().toISOString(),
    kind: 'post',
    section: '',
    section_label: '',
    tier: 'unjudged',
    score: null,
    why: 'Sent by you. Spyglass will read and assess it in the next pass.',
    key_points: [],
    entities: [],
    signal: null,
    state: { saved: false, opened: false, vote: null, from_user: true, captured_via: 'dashboard', vault_path: null, note: note?.trim() || null },
    has_reader: false,
  }
  current.items = [item, ...current.items]
  return item
}

/** Find the latest thread for an item or a brief day, or create one (always when `fresh`). */
export function threadFor(itemId: number | undefined, briefDay: string | undefined, fresh = false): Thread {
  const current = mockState()
  const existing = [...current.threads]
    .reverse()
    .find((thread) =>
      itemId !== undefined ? thread.item_id === itemId : briefDay !== undefined ? thread.brief_day === briefDay : thread.item_id === null && thread.brief_day === null,
    )
  if (existing && !fresh) return existing
  const now = new Date().toISOString()
  const thread: Thread = {
    id: current.threads.length + 1,
    item_id: itemId ?? null,
    brief_day: itemId !== undefined ? null : briefDay ?? null,
    title: itemId !== undefined ? 'Questions about this item' : briefDay !== undefined ? 'Questions about the brief' : 'Questions about your feed',
    engine: null,
    model: null,
    created_at: now,
    updated_at: now,
  }
  current.threads = [...current.threads, thread]
  return thread
}

/** Append a message to a thread and return it with its new id. */
export function addMessage(message: Omit<AssistMessage, 'id' | 'created_at'>, threadId: number): AssistMessage {
  const current = mockState()
  const stored: AssistMessage = { ...message, id: current.nextMessageId++, created_at: new Date().toISOString() }
  current.messages = [...current.messages, { threadId, message: stored }]
  return stored
}

/** Messages of one thread, oldest first. */
export function messagesOf(threadId: number): AssistMessage[] {
  return mockState()
    .messages.filter((entry) => entry.threadId === threadId)
    .map((entry) => entry.message)
}
