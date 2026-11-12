// GroupHeading: the small-caps heading of one Watch group, with how much it brought in this week (a link
// to those items in the Feed) and its menu.
import { buildHash } from '../../router'
import { Button, IconButton, IconMore, Menu, SectionHeading, type MenuItem } from '../../ui'
import type { OrganizedGroup } from './organize'
import { weekText } from './weekText'

export type GroupMenuAction = 'pause' | 'resume' | 'rename' | 'move' | 'remove'

export interface GroupHeadingProps {
  id: string
  group: OrganizedGroup
  busy: boolean
  onAction: (action: GroupMenuAction) => void
}

/** The heading row: name, then either "Paused" with Resume or the weekly count, then the group menu. */
export function GroupHeading({ id, group, busy, onAction }: GroupHeadingProps) {
  const items: MenuItem[] = [
    ...(group.paused ? [] : [{ id: 'pause', label: 'Pause this group', onSelect: () => onAction('pause') }]),
    { id: 'rename', label: 'Rename group…', onSelect: () => onAction('rename') },
    { id: 'move', label: 'Move all to another group…', onSelect: () => onAction('move') },
    { id: 'remove', label: 'Remove this group…', onSelect: () => onAction('remove') },
  ]
  const note = (
    <span className="rw-group-note">
      {group.paused ? (
        <>
          <span>Paused</span>
          <Button size="sm" variant="quiet" disabled={busy} aria-label={`Resume ${group.name}`} onClick={() => onAction('resume')}>
            Resume
          </Button>
        </>
      ) : (
        weekText(group.weekCount) &&
        (group.weekCount ? (
          // The Feed lists exactly the items this number counts.
          <a className="rw-group-link" href={buildHash({ name: 'feed', params: { watch_group: group.name } })} title="Show these items in the Feed">
            {weekText(group.weekCount)}
          </a>
        ) : (
          <span>{weekText(group.weekCount)}</span>
        ))
      )}
      <Menu
        label={`Actions for the group ${group.name}`}
        items={items}
        trigger={<IconButton label={`Actions for the group ${group.name}`} icon={<IconMore size={16} />} size="sm" disabled={busy} />}
      />
    </span>
  )
  return (
    <SectionHeading id={id} note={note}>
      {group.name}
    </SectionHeading>
  )
}
