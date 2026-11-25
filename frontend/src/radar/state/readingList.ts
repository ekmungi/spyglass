// The reading list: the label, the ordered item ids and the page of the list the reader last opened
// an item from (Today, the Feed), so the reader can move to the previous and next story. It lives in
// memory for the session only.
import { useSyncExternalStore } from 'react'

/** The page a reading list belongs to, named as its route is ("today", "feed"). */
export type ReadingOrigin = 'today' | 'feed'

export interface ReadingList {
  /** How the list is named in the reader, such as "Today" or "the Feed". */
  label: string
  ids: number[]
  /**
   * The page that set the list. The reader uses the list only when it was opened from this page, so
   * a list left over from Today does not drive a reader opened from Watch.
   */
  origin: ReadingOrigin
}

/** Where one item sits in a reading list. */
export interface ReadingPosition {
  /** Zero-based position of the item; show `index + 1` to the reader ("2 of 27"). */
  index: number
  total: number
  previous: number | null
  next: number | null
}

let current: ReadingList | null = null
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/**
 * Replace the reading list with `ids`, named `label`, as set by the page `origin`. The ids are
 * copied, so later changes to the caller's array do not move it.
 */
export function setReadingList(label: string, ids: number[], origin: ReadingOrigin): void {
  current = { label, ids: [...ids], origin }
  emit()
}

/** Forget the reading list (tests, or a fresh start). */
export function resetReadingList(): void {
  current = null
  emit()
}

/** React hook: the current reading list, or null before any list was set; re-renders when it changes. */
export function useReadingList(): ReadingList | null {
  return useSyncExternalStore(subscribe, () => current, () => current)
}

/**
 * Where `id` sits in `list`: its zero-based index, the length of the list, and the ids before and
 * after it (null at either end). Null when there is no list or the id is not in it.
 */
export function neighbours(list: ReadingList | null, id: number): ReadingPosition | null {
  if (!list) return null
  const index = list.ids.indexOf(id)
  if (index < 0) return null
  return {
    index,
    total: list.ids.length,
    previous: index > 0 ? list.ids[index - 1] : null,
    next: index < list.ids.length - 1 ? list.ids[index + 1] : null,
  }
}
