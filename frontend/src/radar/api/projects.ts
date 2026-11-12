// projects: reading and saving the list of vault projects the assistant may mention. A 404 from the
// service (an older copy without this endpoint) is an answer, not a failure: it reads as null.
import { getProjects, putProjects } from './client'
import { isMissing } from './errors'
import type { ProjectRow } from './types'

/** The projects, or null when this copy of the service has no projects endpoint yet. */
export async function loadProjects(signal?: AbortSignal): Promise<ProjectRow[] | null> {
  try {
    return await getProjects(signal)
  } catch (cause) {
    if (isMissing(cause)) return null
    throw cause
  }
}

/** Save the one-line descriptions: only projects with a line are sent; the rest stay private. */
export async function saveProjects(rows: readonly ProjectRow[]): Promise<ProjectRow[]> {
  const described = rows.filter((row) => row.description.trim()).map((row) => ({ name: row.name, description: row.description.trim() }))
  return putProjects({ projects: described })
}
