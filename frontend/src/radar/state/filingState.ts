// Filing state: which items wait in the To file queue, applied optimistically on top of what the
// service last sent, plus the number of waiting items. Queuing writes nothing into the vault and
// opens nothing; a later "File now" opens one Claude Code session for the whole queue.
import { useSyncExternalStore } from 'react'
import { getFilingQueue, queueForFiling, unqueueFiling } from '../api/client'
import { errorMessage, isMissing } from '../api/errors'
import type { FilingChoice, FilingOverview, FilingResult } from '../api/types'
import { toast } from '../ui/toastStore'
import { noteFilingOverview, resetFilingConfigured } from './filingConfigured'

type Filing = 'waiting' | null

/** The toast shown after an item is queued. */
export const QUEUED_TOAST = 'Added to the filing queue'

let overrides: ReadonlyMap<number, Filing> = new Map()
let count: number | null = null
// The ids the service listed as waiting the last time it was asked; null until then. It corrects
// cached lists that still show an item as waiting after the filing session has filed it.
let waitingIds: ReadonlySet<number> | null = null
// Changes on every update, so a hook can re-render when any of the above changes.
let version = 0
const listeners = new Set<() => void>()

function emit(): void {
  version += 1
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Replace the override for one item (a new Map each time; nothing is mutated in place). */
function setOverride(id: number, value: Filing | undefined): void {
  const next = new Map(overrides)
  if (value === undefined) next.delete(id)
  else next.set(id, value)
  overrides = next
  emit()
}

/** Remember how many items wait, as the service last reported. */
export function setFilingCount(value: number | null): void {
  count = value
  emit()
}

/** Forget all local filing state (tests, and after a full reload of data). */
export function resetFilingState(): void {
  overrides = new Map()
  count = null
  waitingIds = null
  resetFilingConfigured()
  emit()
}

/** The effective filing mark of an item: the local change, else the service's last list, else `base`. */
export function effectiveFiling(id: number, base: Filing | undefined): Filing {
  if (overrides.has(id)) return overrides.get(id) as Filing
  if (waitingIds !== null) return waitingIds.has(id) ? 'waiting' : null
  return base ?? null
}

/** React hook: an item's filing mark, re-rendering when it changes anywhere. */
export function useFiling(id: number, base: Filing | undefined): Filing {
  useSyncExternalStore(subscribe, () => version, () => version)
  return effectiveFiling(id, base)
}

/** React hook: a number that changes whenever any filing state changes (for memoised lists). */
export function useFilingVersion(): number {
  return useSyncExternalStore(subscribe, () => version, () => version)
}

/** React hook: how many items wait (null until it is known). */
export function useFilingCount(): number | null {
  return useSyncExternalStore(subscribe, () => count, () => count)
}

/** Ask the service how many items wait; a service without the queue counts as none. */
export async function loadFilingCount(signal?: AbortSignal): Promise<void> {
  try {
    const queue = await getFilingQueue(signal)
    if (signal?.aborted) return
    // The same reply carries the "is filing set up" flag; keep it current without another request.
    noteFilingOverview(queue as FilingOverview)
    waitingIds = new Set(queue.waiting.map((entry) => entry.item.id))
    overrides = new Map()
    setFilingCount(queue.count)
  } catch (error) {
    if (signal?.aborted) return
    if (isMissing(error)) {
      waitingIds = new Set()
      setFilingCount(0)
    }
    // Any other failure leaves the number as it was; the queue is a convenience on this page.
  }
}

/** Keep the number in step with a reply from the service. */
function applyResult(result: FilingResult | null): void {
  if (result && typeof result.count === 'number') setFilingCount(result.count)
}

/** Remember that the service now lists the item as waiting (or no longer does). */
function noteWaiting(id: number, waiting: boolean): void {
  if (waitingIds === null) return
  const next = new Set(waitingIds)
  if (waiting) next.add(id)
  else next.delete(id)
  waitingIds = next
}

/**
 * Put an item in the To file queue (or change its choices), at once. On success a toast offers
 * Undo; on failure the mark is rolled back with an error toast offering Retry. Resolves true on
 * success. `base` is the mark the caller currently shows, so a rollback restores it.
 */
export async function queueItem(id: number, choice: FilingChoice = {}, options: { quiet?: boolean } = {}): Promise<boolean> {
  const previous = overrides.has(id) ? overrides.get(id) : undefined
  setOverride(id, 'waiting')
  try {
    applyResult(await queueForFiling(id, choice))
    noteWaiting(id, true)
  } catch (error) {
    setOverride(id, previous)
    toast(`Could not add this to the filing queue. ${errorMessage(error)}`, {
      tone: 'error',
      action: { label: 'Retry', onClick: () => void queueItem(id, choice, options) },
    })
    return false
  }
  if (!options.quiet) toast(QUEUED_TOAST, { action: { label: 'Undo', onClick: () => void unqueueItem(id, { quiet: true }) } })
  return true
}

/** Take an item out of the queue, at once; a failure rolls the mark back with an error toast. */
export async function unqueueItem(id: number, options: { quiet?: boolean } = {}): Promise<boolean> {
  const previous = overrides.has(id) ? overrides.get(id) : undefined
  setOverride(id, null)
  try {
    applyResult(await unqueueFiling(id))
    noteWaiting(id, false)
  } catch (error) {
    setOverride(id, previous)
    toast(`Could not remove this from the filing queue. ${errorMessage(error)}`, {
      tone: 'error',
      action: { label: 'Retry', onClick: () => void unqueueItem(id, options) },
    })
    return false
  }
  if (!options.quiet) toast('Removed from the filing queue')
  return true
}
