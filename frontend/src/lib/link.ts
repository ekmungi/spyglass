// The linked Claude session from the dashboard's side: what to copy for the
// session when it is already open, since nothing can type into a Claude session from outside.
import { formatAge } from './dates'
import type { LinkStatus } from './types'

// After this long, a new session that has not linked has most likely opened outside the vault.
export const LINK_SLOW_MS = 90 * 1000

/** The header indicator's words. */
export function linkLine(status: LinkStatus | null, now: number = Date.now()): string {
  const heard = status?.last_seen ? `, last heard ${formatAge(status.last_seen)}` : ''
  if (status?.linked) {
    return status.waiting ? 'Linked to Claude, a new session is waiting to link' : `Linked to Claude${heard}`
  }
  if (status?.waiting) {
    const since = status.waiting_since ? Date.parse(status.waiting_since) : NaN
    if (now - since > LINK_SLOW_MS) {
      return 'The new Claude session has not linked. Check its folder chip shows your vault, then press Enter'
    }
    return 'Waiting for the new Claude session'
  }
  if (status?.idle) return `Linked session idle${heard}`
  if (status?.ended === 'closed') return 'Link ended when Spyglass closed'
  if (status?.ended === 'ended') return 'Link ended'
  return 'No linked Claude session'
}

/** The text to paste into the linked session: the task (if any), then the item codes. */
export function referenceText(cardIds: number[], task?: string): string {
  const codes = cardIds.map((id) => `#${id}`).join(', ')
  if (!task) return codes
  return codes ? `${task}\n\nItems: ${codes}` : task
}

/** Copy text to the clipboard; false when the browser refuses. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
