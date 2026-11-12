// UnopenedLine: one quiet line under the masthead's meta line naming the briefs of the last week
// that were never opened, each date a link to that day. Nothing when there are none.
import { navigate } from '../router'
import { unopenedParts } from './unopened'

/** "You have not opened the brief of 11 November" / "…the briefs of 10 and 11 November". */
export function UnopenedLine({ days }: { days: string[] }) {
  const parts = unopenedParts(days)
  if (!parts.length) return null
  return (
    <p className="r-masthead__unopened">
      You have not opened the {parts.length === 1 ? 'brief' : 'briefs'} of{' '}
      {parts.map((part, index) => (
        <span key={part.day}>
          {index > 0 && (index === parts.length - 1 ? ' and ' : ', ')}
          <a
            href={`#/today/${part.day}`}
            onClick={(event) => {
              event.preventDefault()
              navigate({ name: 'today', day: part.day })
            }}
          >
            {part.text}
          </a>
        </span>
      ))}
    </p>
  )
}
