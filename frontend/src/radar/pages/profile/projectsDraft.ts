// projectsDraft: the longest allowed line and the comparison that decides whether the projects list
// has unsaved edits.
import type { ProjectRow } from '../../api/types'

/** The longest one-line description the AI may see. */
export const MAX_DESCRIPTION = 200

/** True when two lists name the same projects with the same lines (what "unsaved" means here). */
export function sameProjects(a: readonly ProjectRow[], b: readonly ProjectRow[]): boolean {
  return a.length === b.length && a.every((row, index) => row.name === b[index].name && row.description === b[index].description)
}
