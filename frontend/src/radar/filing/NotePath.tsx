// NotePath and NoteName: a vault place as folder segments that wrap only between folders, and a
// note's file name cut in the middle (the full name in its title). Used by the plan and Filed recently.
import { pathSegments, splitForMiddleTruncation } from './notePathText'

/** "Papers / Medicine", each folder unbroken; a too-long folder ends in an ellipsis. */
export function NotePath({ path }: { path: string }) {
  const segments = pathSegments(path)
  if (!segments.length) return null
  return (
    <span className="r-notepath" title={segments.join(' / ')}>
      {segments.map((segment, index) => (
        <span key={`${index}-${segment}`} className="r-notepath__part">
          {index > 0 && <span className="r-notepath__sep"> / </span>}
          <span className="r-notepath__name">{segment}</span>
        </span>
      ))}
    </span>
  )
}

/** A file name in the quiet monospace, its middle cut when the column is narrow. */
export function NoteName({ name }: { name: string }) {
  const { head, tail } = splitForMiddleTruncation(name)
  return (
    <span className="r-notename" title={name}>
      <span className="r-notename__head">{head}</span>
      {tail && <span className="r-notename__tail">{tail}</span>}
    </span>
  )
}
