// claudeStore: which item the "Open in Claude Code" dialog is open for. The reader's More menu, the
// summary block and the assistant all open the same dialog through here, so it exists once.
import { useSyncExternalStore } from 'react'
import type { ClaudeIntent } from '../api/types'

export interface ClaudeDialogRequest {
  itemId: number
  /** Start on this choice instead of the default. */
  intent?: ClaudeIntent
  /** Changes with every opening, so the dialog starts fresh each time. */
  token: number
}

let current: ClaudeDialogRequest | null = null
let counter = 0
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((listener) => listener())
}

/** Open the dialog for one item. */
export function openClaudeDialog(request: Omit<ClaudeDialogRequest, 'token'>): void {
  counter += 1
  current = { ...request, token: counter }
  emit()
}

/** Close the dialog. */
export function closeClaudeDialog(): void {
  if (current === null) return
  current = null
  emit()
}

/** The open request, or null while the dialog is closed. */
export function getClaudeDialog(): ClaudeDialogRequest | null {
  return current
}

/** React hook: the open request, or null. */
export function useClaudeDialog(): ClaudeDialogRequest | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    () => current,
    () => current,
  )
}

/** The choice a request starts on: the one the opener asked for, otherwise Discuss. */
export function startingIntent(request: Pick<ClaudeDialogRequest, 'intent'>): ClaudeIntent {
  return request.intent ?? 'discuss'
}
