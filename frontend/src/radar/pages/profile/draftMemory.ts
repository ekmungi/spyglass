// Draft memory: unsaved profile edits survive leaving the page, so a click on another page in the
// rail never silently throws away what the reader typed.
import type { Profile } from '../../api/types'

interface Remembered {
  /** The saved version the edits were made against. */
  version: number
  draft: Profile
}

let remembered: Remembered | null = null

/** Keep the draft for later. */
export function rememberDraft(version: number, draft: Profile): void {
  remembered = { version, draft }
}

/** The remembered draft, only if it was made against the same saved version. */
export function recallDraft(version: number): Profile | null {
  return remembered && remembered.version === version ? remembered.draft : null
}

/** Forget any remembered draft (after a save, a discard, or in tests). */
export function forgetDraft(): void {
  remembered = null
}
