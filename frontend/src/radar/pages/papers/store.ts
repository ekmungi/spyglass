// Memory for the Find papers page: the last search and its results live here, outside the
// component, so leaving the page and coming back (or leaving mid-search) loses nothing.
import { errorMessage } from '../../api/errors'
import type { PapersResponse, PaperResult } from '../../api/types'

export type SearchStatus = 'idle' | 'loading' | 'done' | 'error'

export interface PapersSnapshot {
  topic: string
  status: SearchStatus
  papers: readonly PaperResult[]
  error: string | null
  /** The service's sentence about a degraded or empty search, shown above the results. */
  notice: string | null
  /** Paper URL -> id of the feed item created by "Add to my feed". */
  added: Readonly<Record<string, number>>
}

const EMPTY: PapersSnapshot = { topic: '', status: 'idle', papers: [], error: null, notice: null, added: {} }

let snapshot: PapersSnapshot = EMPTY
let sequence = 0
const listeners = new Set<() => void>()

function publish(next: PapersSnapshot): void {
  snapshot = next
  listeners.forEach((listener) => listener())
}

/** Subscribe to changes (for useSyncExternalStore); returns the unsubscribe function. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The current immutable snapshot (for useSyncExternalStore). */
export function getSnapshot(): PapersSnapshot {
  return snapshot
}

/**
 * Run a search and keep its outcome. A newer search supersedes an older one, so a slow reply can
 * never overwrite a fresher result.
 */
export async function runSearch(topic: string, search: (topic: string) => Promise<PapersResponse>): Promise<void> {
  const mine = ++sequence
  publish({ ...snapshot, topic, status: 'loading', papers: [], error: null, notice: null })
  try {
    const reply = await search(topic)
    if (mine !== sequence) return
    publish({ ...snapshot, status: 'done', papers: reply.papers ?? [], error: null, notice: reply.notice?.trim() || null })
  } catch (cause) {
    if (mine !== sequence) return
    publish({ ...snapshot, status: 'error', papers: [], error: errorMessage(cause), notice: null })
  }
}

/** Remember that a paper was added to the feed, and which item it became. */
export function markAdded(url: string, itemId: number): void {
  publish({ ...snapshot, added: { ...snapshot.added, [url]: itemId } })
}

/** Forget everything (used by tests). */
export function resetPapersMemory(): void {
  sequence += 1
  publish(EMPTY)
}
