// Plain-language text for the Watch review: what was applied.
import type { WatchApplyCounts } from '../../api/types'

/** "Paused 2, removed 1, added 1" for the counts an apply reports; "Nothing changed" when all are zero. */
export function describeApplied(counts: WatchApplyCounts): string {
  const parts = [
    counts.paused > 0 ? `paused ${counts.paused}` : '',
    counts.removed > 0 ? `removed ${counts.removed}` : '',
    counts.added > 0 ? `added ${counts.added}` : '',
    counts.regrouped > 0 ? `moved ${counts.regrouped} to another group` : '',
    counts.merged > 0 ? `merged ${counts.merged} into other groups` : '',
  ].filter(Boolean)
  if (parts.length === 0) return 'Nothing changed'
  const text = parts.join(', ')
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`
}
