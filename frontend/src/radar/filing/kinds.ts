// kinds: the four kinds of note an item can be filed as, with the words the reader sees.
import type { FilingKind } from '../api/types'

/** The "File it as" choices. */
export const KIND_CHOICES: { value: FilingKind; label: string }[] = [
  { value: 'resource', label: 'Resource' },
  { value: 'to explore', label: 'To explore' },
  { value: 'learning', label: 'Learning' },
  { value: 'feature idea', label: 'Feature idea' },
]
