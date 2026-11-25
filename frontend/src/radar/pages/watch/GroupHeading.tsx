// GroupHeading: the head of one Watch group's row: its name, the group menu (which also moves the
// group up or down the page), and how much it brought in this week (a link to those items in the Feed).
import { buildHash } from '../../router'
import { IconButton, IconMore, Menu, type MenuItem } from '../../ui'
import type { LayoutGroup } from './organize'
import { weekText } from './weekText'

export type GroupMenuAction = 'pause' | 'resume' | 'up' | 'down' | 'rename' | 'move' | 'remove'

export interface GroupHeadingProps {
  /** The heading's id, which labels the group's row. */
  id: string
  group: LayoutGroup
  /** None of the group's names is watched right now (each was paused on this visit). */
  paused: boolean
  /** The first or last group shown, which cannot move further up or down. */
  first: boolean
  last: boolean
  busy: boolean
  onAction: (action: GroupMenuAction) => void
}

/** The group's menu: pause or watch again, the two moves, then rename, move all and remove. */
function groupMenu({ paused, first, last, onAction }: Pick<GroupHeadingProps, 'paused' | 'first' | 'last' | 'onAction'>): MenuItem[] {
  return [
    paused
      ? { id: 'resume', label: 'Watch this group again', onSelect: () => onAction('resume') }
      : { id: 'pause', label: 'Pause this group', onSelect: () => onAction('pause') },
    { id: 'up', label: 'Move up', disabled: first, onSelect: () => onAction('up') },
    { id: 'down', label: 'Move down', disabled: last, onSelect: () => onAction('down') },
    { id: 'rename', label: 'Rename group…', onSelect: () => onAction('rename') },
    { id: 'move', label: 'Move all to another group…', onSelect: () => onAction('move') },
    { id: 'remove', label: 'Remove this group…', onSelect: () => onAction('remove') },
  ]
}

/** The name as a heading with its menu beside it, and the weekly count on the line below. */
export function GroupHeading({ id, group, paused, first, last, busy, onAction }: GroupHeadingProps) {
  const week = weekText(group.weekCount)
  return (
    <>
      <div className="rw-group__title">
        <h3 className="rw-group__name" id={id}>
          {group.name}
        </h3>
        <Menu
          label={`Actions for the group ${group.name}`}
          align="start"
          items={groupMenu({ paused, first, last, onAction })}
          trigger={
            <IconButton className="rw-group__more" label={`Actions for the group ${group.name}`} icon={<IconMore size={16} />} size="sm" disabled={busy} />
          }
        />
      </div>
      {week && (
        <div className="rw-group__meta">
          {group.weekCount ? (
            // The Feed lists exactly the items this number counts.
            <a className="rw-group-link" href={buildHash({ name: 'feed', params: { watch_group: group.name } })} title="Show these items in the Feed">
              {week}
            </a>
          ) : (
            <span>{week}</span>
          )}
        </div>
      )}
    </>
  )
}
