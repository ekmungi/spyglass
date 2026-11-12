// FilingLine: one quiet line under the masthead's meta about background filing ("Filed yesterday: 9
// items. 2 questions are open." or "Filing has not run since Tuesday: Obsidian was closed."), with a
// link to the Feed's To file view. Nothing when the service has nothing to say.
import { navigate } from '../router'
import { useFilingConfigured } from '../state/filingConfigured'

/** The line, or nothing for an empty text or when filing is not set up. */
export function FilingLine({ text }: { text: string | null }) {
  const configured = useFilingConfigured()
  if (!text || !configured) return null
  return (
    <p className="r-masthead__filing">
      {text}{' '}
      <a
        href="#/feed?filing=waiting"
        onClick={(event) => {
          event.preventDefault()
          navigate({ name: 'feed', params: { filing: 'waiting' } })
        }}
      >
        Open To file
      </a>
    </p>
  )
}
