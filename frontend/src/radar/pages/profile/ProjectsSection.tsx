// ProjectsSection: "Your projects" on the Profile page. The assistant may tell the reader that an item
// could help a project, but it only ever sees the name and the one line written here; a project with
// no line stays private, so the list shows only the projects that have a line until the reader asks for
// the others. The page holds the lines (useProjectsDraft) and its one Save bar saves them.
import { useState } from 'react'
import { useStayListed } from '../../hooks/useStayListed'
import { Button, SectionHeading, Skeleton } from '../../ui'
import { MAX_DESCRIPTION } from './projectsDraft'
import { isShared, type ProjectsDraft } from './useProjectsDraft'

export interface ProjectsSectionProps {
  /** The projects as the page holds them: loaded rows, unsaved edits and the edit function. */
  projects: ProjectsDraft
}

/** The Your projects section: the rows and their lines; saving is the page's job. */
export function ProjectsSection({ projects }: ProjectsSectionProps) {
  const { load, saved, current, sharedCount, edit } = projects
  const [showAll, setShowAll] = useState(false)
  // The projects the reader typed into during this visit. They stay listed while the list is folded, so a
  // row does not vanish under the cursor when its line is emptied, until the reader folds or unfolds the list.
  const touched = useStayListed<string>()
  const listedWhenFolded = current.filter((row) => isShared(row) || touched.pinned.has(row.name))
  const others = current.length - listedWhenFolded.length
  // Unfolded, the fold button stays while any row has no line, even when the reader typed into each of them.
  const offerFold = showAll ? current.some((row) => !isShared(row)) : others > 0

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
        {!showAll && !current.some(isShared) && <p className="r-meta rpr-empty">No project has a line yet, so the AI sees none of them.</p>}
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
                        touched.pin(row.name, true)
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
        {offerFold && (
          <Button
            variant="quiet"
            size="sm"
            className="rpr-more"
            onClick={() => {
              setShowAll((all) => !all)
              touched.release()
            }}
          >
            {showAll ? 'Show only the shared projects' : others === 1 ? 'Show the other project' : `Show the other ${others} projects`}
          </Button>
        )}
      </>
    )
  }

  // The count says what the assistant sees now, so it is read from the saved rows, not from the edits.
  return (
    <section aria-labelledby="profile-projects" className="rpr-section">
      <SectionHeading id="profile-projects" note={saved !== null && saved.length > 0 ? `${sharedCount} of ${saved.length} shared with the AI` : 'Optional'}>
        Your projects
      </SectionHeading>
      <p className="rpr-lede r-meta">
        The assistant can tell you when an item could help one of these projects. Only projects you describe here are ever mentioned to the AI, and
        only their name and your one line.
      </p>
      {body}
    </section>
  )
}
