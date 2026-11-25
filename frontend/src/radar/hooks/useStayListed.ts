// useStayListed: the rows the reader changed during this visit, each with the place it had when first
// changed. A list that sorts or folds its rows by their state uses it to keep such a row where it was,
// with the focus, instead of moving or hiding it under the cursor.
import { useCallback, useState } from 'react'

export interface StayListed<K, P> {
  /** Each changed row's key, with the place it had when the reader first changed it. */
  pinned: ReadonlyMap<K, P>
  /** Remember that the row `key` changed while it was in `place`; a row already remembered keeps its first place. */
  pin: (key: K, place: P) => void
  /** Forget every row. Call it when the reader folds or unfolds the list; a new visit starts empty anyway. */
  release: () => void
}

/** Rows changed during this visit; `P` is the place a row is kept in (`true` for a list with one place). */
export function useStayListed<K, P = true>(): StayListed<K, P> {
  const [pinned, setPinned] = useState<ReadonlyMap<K, P>>(() => new Map())
  const pin = useCallback((key: K, place: P) => setPinned((rows) => (rows.has(key) ? rows : new Map(rows).set(key, place))), [])
  const release = useCallback(() => setPinned(new Map()), [])
  return { pinned, pin, release }
}
