// useProjectNames: the names of the reader's vault projects, for the project pickers.
import { useEffect, useState } from 'react'
import { loadProjects } from '../api/projects'

/** Names of the projects found in the vault (empty while loading, when there are none, or when the list is not available). */
export function useProjectNames(): string[] {
  const [names, setNames] = useState<string[]>([])
  useEffect(() => {
    const controller = new AbortController()
    loadProjects(controller.signal).then(
      (rows) => {
        if (!controller.signal.aborted) setNames((rows ?? []).filter((row) => row.in_vault).map((row) => row.name))
      },
      () => undefined, // The list is a convenience: without it, an item can still be queued with no project.
    )
    return () => controller.abort()
  }, [])
  return names
}
