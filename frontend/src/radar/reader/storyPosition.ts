// The reading list as seen from the reader: where the open item sits in the list it was
// opened from, the move to another story, and the J (next) and K (previous) keys.
import { useEffect } from 'react'
import { isTypingTarget } from '../hooks/useListKeys'
import { navigate } from '../router'
import { neighbours, useReadingList, type ReadingPosition } from '../state/readingList'

/** Where the open item sits, with the list's label ("Today", "the Feed"). */
export interface StoryPosition extends ReadingPosition {
  label: string
}

/** React hook: the open item's place in the reading list, or null without a list or outside it. */
export function useStoryPosition(id: number): StoryPosition | null {
  const list = useReadingList()
  const position = neighbours(list, id)
  return list && position ? { ...position, label: list.label } : null
}

/**
 * Open another story of the list in place of this one. The history entry is replaced, and the
 * router keeps the page the first reader was opened from, so Back leaves the reader in one step
 * however many stories were read.
 */
export function moveToStory(id: number): void {
  navigate({ name: 'item', id }, { replace: true })
}

/** True when a key press belongs to an open dialog or menu, which take their own keys. */
function insideOverlay(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest('[role="dialog"], [role="menu"]') !== null
}

/**
 * React hook: J opens the next story and K the previous one, on the window. Ignored while typing (the
 * assistant's composer shares the screen), inside a dialog or menu, with a modifier key held, or
 * when the item is not in a reading list.
 */
export function useStoryKeys(id: number): void {
  const position = useStoryPosition(id)
  const previous = position?.previous ?? null
  const next = position?.next ?? null
  useEffect(() => {
    if (previous === null && next === null) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return
      if (isTypingTarget(event.target) || insideOverlay(event.target)) return
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
