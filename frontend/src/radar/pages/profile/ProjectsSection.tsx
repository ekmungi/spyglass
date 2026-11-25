// ProjectsSection: "Your projects" on the Profile page. The assistant may tell the reader that an item
// could help a project, but it only ever sees the name and the one line written here; a project with
// no line stays private, so the list shows only the projects that have a line until the reader asks for
// the others. One Save for the section, like the rest of the page aware of unsaved edits.
import { useEffect, useState } from 'react'
import { errorMessage } from '../../api/errors'
import type { ProjectRow } from '../../api/types'
import { Button, SectionHeading, Skeleton } from '../../ui'
import { loadProjects, saveProjects } from './api'
import { MAX_DESCRIPTION, sameProjects } from './projectsDraft'
import { useLoad } from '../sources/useLoad'

export interface ProjectsSectionProps {
  /** Called with the number of projects that have a line, now and after every edit (for the tab count). */
  onSharedChange?: (count: number) => void
}

/** Whether a project has a line, which is what makes it visible to the AI. */
const isShared = (row: ProjectRow) => row.description.trim() !== ''

/** The Your projects section; loads, edits and saves on its own. */
export function ProjectsSection({ onSharedChange }: ProjectsSectionProps = {}) {
  const load = useLoad<ProjectRow[] | null>((signal) => loadProjects(signal))
  const saved = load.data
  const [draft, setDraft] = useState<ProjectRow[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [outcome, setOutcome] = useState<{ ok: boolean; message: string } | null>(null)
  const [showAll, setShowAll] = useState(false)
  // Names of the projects the reader typed into since the last save or discard. They stay listed while the
  // list is folded, so a row does not vanish under the cursor when its line is emptied or just written.
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set())
  const current = draft ?? saved ?? []
  const dirty = saved !== null && draft !== null && !sameProjects(draft, saved)
  const sharedCount = current.filter(isShared).length
  const listedWhenFolded = current.filter((row) => isShared(row) || touched.has(row.name))
  const others = current.length - listedWhenFolded.length

  useEffect(() => {
    if (saved !== null) onSharedChange?.(sharedCount)
  }, [saved, sharedCount, onSharedChange])

  useEffect(() => {
    if (!dirty) return
    // The browser's own "leave this page?" prompt, for closing the tab or reloading with unsaved edits.
    const guard = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])

  const edit = (update: (rows: ProjectRow[]) => ProjectRow[]) => {
    setDraft(update(current))
    setOutcome(null)
  }

  const reset = () => {
    setDraft(null)
    setTouched(new Set())
    setOutcome(null)
  }

  const save = async () => {
    setSaving(true)
    setOutcome(null)
    try {
      const rows = await saveProjects(current)
      load.replace(rows)
      setDraft(null)
      setTouched(new Set())
      setOutcome({ ok: true, message: 'Saved. The assistant may now mention the projects you described.' })
    } catch (cause) {
      setOutcome({ ok: false, message: errorMessage(cause) })
    } finally {
      setSaving(false)
    }
  }

  let body
  if (load.error && !load.data) {
    body = (
      <div className="rpr-error" role="alert">
        <p className="r-error-text">{load.error}</p>
        <Button onClick={load.reload}>Try again</Button>
      </div>
    )
  } else if (load.loading && saved === null) {
    body = (
      <div aria-busy="true" aria-label="Loading your projects">
        <Skeleton lines={3} />
      </div>
    )
  } else if (saved === null) {
    body = <p className="r-meta rpr-empty">Projects are not available in this copy of Spyglass yet.</p>
  } else if (current.length === 0) {
    body = <p className="r-meta rpr-empty">No projects were found in your vault yet.</p>
  } else {
    const listed = showAll ? current : listedWhenFolded
    body = (
      <>
        {!showAll && sharedCount === 0 && <p className="r-meta rpr-empty">No project has a line yet, so the AI sees none of them.</p>}
        <ul className="r-rows">
          {current.map((row, index) =>
            listed.includes(row) ? (
              <li key={row.name} className="rpr-row">
                <div className="rpr-project">
                  <span className="rpr-project__name">{row.name}</span>
                  <div className="rpr-project__line">
                    <label htmlFor={`project-line-${index}`} className="r-sr-only">
                      One line about {row.name}
                    </label>
                    <input
                      id={`project-line-${index}`}
                      className="r-input"
                      value={row.description}
                      maxLength={MAX_DESCRIPTION}
                      placeholder="One line the AI may see. Leave empty to keep this project private."
                      onChange={(event) => {
                        const value = event.target.value
                        setTouched((names) => new Set(names).add(row.name))
                        edit((rows) => rows.map((entry, i) => (i === index ? { ...entry, description: value } : entry)))
                      }}
                    />
                    {!row.in_vault && <span className="r-meta">no longer in your vault</span>}
                  </div>
                  {!row.in_vault && (
                    <Button variant="quiet" size="sm" aria-label={`Remove ${row.name} from the list`} onClick={() => edit((rows) => rows.filter((_, i) => i !== index))}>
                      Remove
                    </Button>
                  )}
                </div>
              </li>
            ) : null,
          )}
        </ul>
        {others > 0 && (
          <Button variant="quiet" size="sm" className="rpr-more" onClick={() => setShowAll((all) => !all)}>
            {showAll ? 'Show only the shared projects' : others === 1 ? 'Show the other project' : `Show the other ${others} projects`}
          </Button>
        )}
      </>
    )
  }

  return (
    <section aria-labelledby="profile-projects" className="rpr-section">
      <SectionHeading id="profile-projects" note={saved !== null && current.length > 0 ? `${sharedCount} of ${current.length} shared with the AI` : 'Optional'}>
        Your projects
      </SectionHeading>
      <p className="rpr-lede r-meta">
        The assistant can tell you when an item could help one of these projects. Only projects you describe here are ever mentioned to the AI, and
        only their name and your one line.
      </p>
      {body}
      {saved !== null && current.length > 0 && (
        <div className="rpr-projects-bar">
          <div className="rpr-savebar__text" role="status" aria-live="polite">
            {outcome ? (
              <span className={outcome.ok ? 'rpr-saved' : 'r-error-text'}>{outcome.message}</span>
            ) : dirty ? (
              <span className="r-meta">You have unsaved changes to your projects.</span>
            ) : null}
          </div>
          <Button
            variant="quiet"
            disabled={!dirty || saving}
            onClick={reset}
          >
            Discard changes
          </Button>
          <Button variant="secondary" disabled={!dirty || saving} onClick={() => void save()}>
            {saving ? 'Saving…' : 'Save projects'}
          </Button>
        </div>
      )}
    </section>
  )
}
