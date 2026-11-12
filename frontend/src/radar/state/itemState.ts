// Item state store: the reader's saved / opened / vote marks, applied optimistically on
// top of whatever the server last sent, so every visible copy of an item updates at once and a
// failed request rolls back.
import { useSyncExternalStore } from 'react'
import { saveItem, unsaveItem, voteItem } from '../api/client'
import { errorMessage } from '../api/errors'
import type { ItemState, Vote } from '../api/types'
import { toast } from '../ui/toastStore'

type Patch = Partial<ItemState>

let overrides: ReadonlyMap<number, Patch> = new Map()
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((listener) => listener())
}

/** Replace the override for one item (a new Map each time; nothing is mutated in place). */
function setOverride(id: number, patch: Patch | undefined): void {
  const next = new Map(overrides)
  if (patch === undefined) next.delete(id)
  else next.set(id, patch)
  overrides = next
  emit()
}

/** The effective state: the server's copy with any local override on top. */
export function effectiveState(id: number, base: ItemState): ItemState {
  const patch = overrides.get(id)
  return patch ? { ...base, ...patch } : base
}

/** Apply a local change to an item's state (merged with earlier local changes). */
export function patchItemState(id: number, patch: Patch): void {
  setOverride(id, { ...(overrides.get(id) ?? {}), ...patch })
}

/** Forget all local changes (tests, or after a full reload of data). */
export function resetItemState(): void {
  overrides = new Map()
  emit()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** React hook: an item's effective state, re-rendering when it changes anywhere. */
export function useItemState(id: number, base: ItemState): ItemState {
  const map = useSyncExternalStore(subscribe, () => overrides, () => overrides)
  const patch = map.get(id)
  return patch ? { ...base, ...patch } : base
}

/**
 * Run an optimistic change: apply `patch` now, call `request`, and restore the previous local
 * state if it fails (with an error toast offering Retry). Resolves true on success.
 */
export async function optimistic(id: number, patch: Patch, request: () => Promise<unknown>, failure: string): Promise<boolean> {
  const previous = overrides.get(id)
  patchItemState(id, patch)
  try {
    await request()
    return true
  } catch (error) {
    setOverride(id, previous)
    toast(`${failure} ${errorMessage(error)}`, {
      tone: 'error',
      action: { label: 'Retry', onClick: () => void optimistic(id, patch, request, failure) },
    })
    return false
  }
}

export interface ItemActionsApi {
  save: (id: number) => Promise<unknown>
  unsave: (id: number) => Promise<unknown>
  vote: (id: number, vote: Vote) => Promise<unknown>
}

const defaultApi: ItemActionsApi = { save: saveItem, unsave: unsaveItem, vote: voteItem }

/** Save or unsave an item, optimistically. `base` is the state the caller currently shows. */
export function toggleSave(id: number, base: ItemState, api: ItemActionsApi = defaultApi): Promise<boolean> {
  const next = !effectiveState(id, base).saved
  return optimistic(id, { saved: next }, () => (next ? api.save(id) : api.unsave(id)), next ? 'Could not save.' : 'Could not remove from saved.')
}

/** Set (or clear, when the same vote is chosen again) the more/less vote, optimistically. */
export function setVote(id: number, base: ItemState, vote: Exclude<Vote, null>, api: ItemActionsApi = defaultApi): Promise<boolean> {
  const next: Vote = effectiveState(id, base).vote === vote ? null : vote
  return optimistic(id, { vote: next }, () => api.vote(id, next), 'Could not record your vote.')
}

/** Mark an item as opened locally (the server records it through the open signal). */
export function markOpened(id: number): void {
  if (!overrides.get(id)?.opened) patchItemState(id, { opened: true })
}
