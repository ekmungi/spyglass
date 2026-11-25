// NextStory: the block at the end of a story that offers the next one of the reading list, such as
// "Next in Today · 3 of 27" with its headline. It opens like the bar's Next story button.
import { buildHash } from '../router'
import { cachedHeadline } from './cachedHeadline'
import { moveToStory, useStoryPosition } from './storyPosition'

/** The link to the next story; nothing without a list or after its last story. */
export function NextStory({ id }: { id: number }) {
  const position = useStoryPosition(id)
  if (!position || position.next === null) return null
  const next = position.next
  const headline = cachedHeadline(next)
  // `index` is zero-based and names this story, so the next one is number index + 2.
  const where = `Next in ${position.label} · ${position.index + 2} of ${position.total}`
  return (
    <a
      className="r-reader-next"
      href={buildHash({ name: 'item', id: next })}
      onClick={(event) => {
        // A modified or middle click keeps the link's own behaviour (a new tab or window).
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
        event.preventDefault()
        moveToStory(next)
      }}
    >
      <span className="r-meta">{where}</span>
      {headline && <span className="r-headline">{headline}</span>}
    </a>
  )
}
