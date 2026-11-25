// The reading list as seen from the reader: where the open item sits in the list it was
// opened from, the move to another story, and the J (next) and K (previous) keys.
import { useEffect } from 'react'
import { isTypingTarget } from '../hooks/useListKeys'
import { navigate, readerOrigin } from '../router'
import { neighbours, useReadingList, type ReadingPosition } from '../state/readingList'

/** Where the open item sits, with the list's label ("Today", "the Feed"). */
export interface StoryPosition extends ReadingPosition {
  label: string
}

/**
 * React hook: the open item's place in the reading list, or null without a list, outside it, or
 * when the reader was opened from another page than the one that set the list (a list left over
 * from Today must not drive a reader opened from Watch). The page the reader was opened from is
 * kept through the replacing moves, so the controls stay while J and K walk the list.
 */
export function useStoryPosition(id: number): StoryPosition | null {
  const list = useReadingList()
  if (!list || readerOrigin()?.name !== list.origin) return null
  const position = neighbours(list, id)
  return position ? { ...position, label: list.label } : null
}

/**
 * Open another story of the list in place of this one. The history entry is replaced, and the
 * router keeps the page the first reader was opened from, so Back leaves the reader in one step
 * however many stories were read.
 */
export function moveToStory(id: number): void {
  navigate({ name: 'item', id }, { replace: true })
}

// Where a key press is someone else's: an editable element (and anything inside one), or an open
// dialog or menu, which take their own keys.
const OWNS_KEYS = '[contenteditable]:not([contenteditable="false"]), [role="dialog"], [role="menu"]'

/** True when a key press is typing or belongs to an editable element, a dialog or a menu. */
function ownsKeys(target: EventTarget | null): boolean {
  return isTypingTarget(target) || (target instanceof Element && target.closest(OWNS_KEYS) !== null)
}

/**
 * React hook: J opens the next story and K the previous one, on the window. Ignored while typing (the
 * assistant's composer shares the screen), in an editable element, a dialog or a menu, with any
 * modifier key held (Shift included), or when the item has no place in a reading list.
 */
export function useStoryKeys(id: number): void {
  const position = useStoryPosition(id)
  const previous = position?.previous ?? null
  const next = position?.next ?? null
  useEffect(() => {
    if (previous === null && next === null) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return
      if (ownsKeys(event.target)) return
      const key = event.key.toLowerCase()
      const target = key === 'j' ? next : key === 'k' ? previous : null
      if (target === null) return
      event.preventDefault()
      moveToStory(target)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [previous, next])
}
