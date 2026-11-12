// NotFound: what an address that names no page shows, with a way back to Today.
import { navigate } from '../router'
import { EmptyState } from '../ui'

/** A small "That page does not exist" state with a link to Today. */
export function NotFound() {
  return (
    <div className="r-page">
      <EmptyState
        title="That page does not exist"
        body="The address may be old or mistyped."
        action={
          <a
            className="r-btn r-btn--secondary"
            href="#/today"
            onClick={(event) => {
              event.preventDefault()
              navigate({ name: 'today' })
            }}
          >
            Go to Today
          </a>
        }
      />
    </div>
  )
}
