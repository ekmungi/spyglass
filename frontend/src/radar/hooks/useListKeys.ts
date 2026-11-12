// useListKeys: j/k to move through a list, Enter to open, s to save; ignored while typing.
import { useEffect, useState } from 'react'

/** True when a key event comes from a text field, so list shortcuts must not fire. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

export interface ListKeyOptions {
  count: number
  enabled: boolean
  onOpen: (index: number) => void
  onSave: (index: number) => void
  /** Container whose rows carry data-row-index, used to scroll the selection into view. */
  container?: HTMLElement | null
}

/** Track the keyboard-selected row (-1 = none) and handle j / k / Enter / s on the window. */
export function useListKeys({ count, enabled, onOpen, onSave, container }: ListKeyOptions): [number, (index: number) => void] {
  const [selected, setSelected] = useState(-1)

  useEffect(() => {
    if (!enabled) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || isTypingTarget(event.target)) return
      if ((event.key === 'j' || event.key === 'k') && count > 0) {
        event.preventDefault()
        const next = event.key === 'j' ? Math.min(count - 1, selected + 1) : Math.max(0, selected - 1)
        setSelected(next)
        const row = container?.querySelector<HTMLElement>(`[data-row-index="${next}"]`)
        // jsdom has no scrollIntoView, hence the optional call.
        row?.scrollIntoView?.({ block: 'nearest' })
        row?.querySelector<HTMLElement>('[data-row-open]')?.focus({ preventScroll: true })
      } else if (event.key === 'Enter' && selected >= 0 && !(event.target instanceof HTMLButtonElement || event.target instanceof HTMLAnchorElement)) {
        event.preventDefault()
        onOpen(selected)
      } else if (event.key === 's' && selected >= 0) {
        event.preventDefault()
        onSave(selected)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [count, enabled, onOpen, onSave, selected, container])

  return [selected, setSelected]
}
