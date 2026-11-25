// useProjectsDraft: the "Your projects" lines as the Profile page holds them. It loads the rows, keeps the
// reader's unsaved edits over them, and saves them through the projects call, so the page's one Save bar
// can save, discard and count them together with the rest of the profile.
import { useState } from 'react'
import type { ProjectRow } from '../../api/types'
import { useLoad, type LoadState } from '../sources/useLoad'
import { loadProjects, saveProjects } from './api'
import { sameProjects } from './projectsDraft'

export interface ProjectsDraft {
  load: LoadState<ProjectRow[] | null>
  /** The rows as the service last confirmed them; null until loaded, and when this copy has no projects. */
  saved: ProjectRow[] | null
  /** The rows as the reader sees them: the unsaved edits over the saved rows. */
  current: ProjectRow[]
  /** True when the reader changed a line or removed a row since the last save or discard. */
  dirty: boolean
  /** How many saved projects have a line, which is what the assistant sees now; null until loaded. */
  sharedCount: number | null
  /** Apply one edit to the current rows. */
  edit: (update: (rows: ProjectRow[]) => ProjectRow[]) => void
  /** Go back to the saved rows. */
  discard: () => void
  /** Send the current rows to the service. Throws when the save fails, and the edits then stay. */
  save: () => Promise<void>
}

/** Whether a project has a line, which is what makes it visible to the AI. */
export const isShared = (row: ProjectRow) => row.description.trim() !== ''

/** The projects of the Profile page: loaded once, edited in memory, saved on the page's Save. */
export function useProjectsDraft(): ProjectsDraft {
  const load = useLoad<ProjectRow[] | null>((signal) => loadProjects(signal))
  const saved = load.data
  const [draft, setDraft] = useState<ProjectRow[] | null>(null)
  const current = draft ?? saved ?? []
  const dirty = saved !== null && draft !== null && !sameProjects(draft, saved)
  const sharedCount = saved === null ? null : saved.filter(isShared).length

  const edit = (update: (rows: ProjectRow[]) => ProjectRow[]) => setDraft(update(current))
  const discard = () => setDraft(null)

  const save = async () => {
    const rows = await saveProjects(current)
    load.replace(rows)
    setDraft(null)
  }

  return { load, saved, current, dirty, sharedCount, edit, discard, save }
}
