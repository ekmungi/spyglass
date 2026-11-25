// ReadingNav: "Previous story" and "Next story" in the reader's bar, with the count such as
// "2 of 27 in Today". Shown only when the item was opened from a list that holds it.
import type { ReactNode } from 'react'
import { IconButton, IconNext, IconPrevious, Tooltip } from '../ui'
import { moveToStory, useStoryPosition } from './storyPosition'

/**
 * One step through the list: an icon button whose tooltip also names its key. At the end it is marked
 * disabled (aria-disabled) and its click does nothing, so the focus stays on it rather than falling to
 * the page, as on the Today pager.
 */
function StepButton({ label, keyName, icon, target }: { label: string; keyName: string; icon: ReactNode; target: number | null }) {
  return (
    <Tooltip label={`${label} (${keyName})`} side="bottom">
      <IconButton
        label={label}
        icon={icon}
        tooltip={false}
        aria-keyshortcuts={keyName}
        aria-disabled={target === null || undefined}
        onClick={() => target !== null && moveToStory(target)}
      />
    </Tooltip>
  )
}

/** Previous, next and the position in the reading list; nothing when the item is in no list. */
export function ReadingNav({ id }: { id: number }) {
  const position = useStoryPosition(id)
  if (!position) return null
  return (
    <span className="r-readerbar__nav">
      <StepButton label="Previous story" keyName="K" icon={<IconPrevious size={18} />} target={position.previous} />
      <StepButton label="Next story" keyName="J" icon={<IconNext size={18} />} target={position.next} />
      <span className="r-meta r-readerbar__count">{`${position.index + 1} of ${position.total} in ${position.label}`}</span>
    </span>
  )
}
