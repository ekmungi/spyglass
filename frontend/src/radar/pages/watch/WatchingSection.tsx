// WatchingSection: the watched names, one row of chips per group in the reader's group order, then
// the collapsed Paused list. It draws the layout it is given; the page decides when that changes.
import { SectionHeading, type MenuItem } from '../../ui'
import type { WatchEntry } from './api'
import { ChipRow } from './ChipRow'
import { GroupHeading, type GroupMenuAction } from './GroupHeading'
import type { LayoutGroup, WatchLayout } from './organize'
import { PausedList } from './PausedList'
import { WatchChip } from './WatchChip'

export interface WatchingSectionProps {
  /** The layout from the last load, with the looks the reader has switched since. */
  layout: WatchLayout
  /** Names whose change is on the way to the server. */
  busyIds: ReadonlySet<number>
  /** The group whose action is on the way, if any. */
  busyGroup: string | null
  /** The chip menu of a name shown under (or labelled with) the given group. */
  menuFor: (entity: WatchEntry, group: string) => MenuItem[]
  onToggle: (entity: WatchEntry) => void
  onGroupAction: (group: LayoutGroup, action: GroupMenuAction) => void
}

/** "62 watched · 8 groups", counting the names as they look now. */
function countLine(layout: WatchLayout): string {
  const shown = [...layout.groups.flatMap((group) => group.entities), ...layout.paused.map((name) => name.entity)]
  const watched = shown.filter((entity) => entity.status === 'active').length
  const groups = layout.groups.length
  return `${watched} watched · ${groups} ${groups === 1 ? 'group' : 'groups'}`
}

/** The section: heading with the count, a key to the two looks, the group rows and the Paused list. */
export function WatchingSection({ layout, busyIds, busyGroup, menuFor, onToggle, onGroupAction }: WatchingSectionProps) {
  const chip = (entity: WatchEntry, group: string, labelled: boolean) => (
    <WatchChip
      key={entity.id}
      entity={entity}
      group={labelled ? group : undefined}
      busy={busyIds.has(entity.id)}
      menu={menuFor(entity, group)}
      onToggle={() => onToggle(entity)}
    />
  )
  return (
    <section aria-labelledby="watch-watching" className="rw-section">
      <SectionHeading id="watch-watching" note={countLine(layout)}>
        Watching
      </SectionHeading>
      <p className="rw-lead">
        <span className="rw-key">
          <span className="rw-dot rw-dot--on" aria-hidden="true" />
          watched
        </span>
        <span className="rw-key">
          <span className="rw-dot rw-dot--off" aria-hidden="true" />
          paused
        </span>
        <span>Click a name to pause it. It turns grey here and, the next time you open the page, it is in Paused below.</span>
      </p>
      {layout.groups.map((group, index) => {
        const id = `watch-group-${index}`
        const quiet = group.entities.every((entity) => entity.status !== 'active')
        const head = (
          <GroupHeading
            id={id}
            group={group}
            paused={quiet}
            first={index === 0}
            last={index === layout.groups.length - 1}
            busy={busyGroup === group.name}
            onAction={(action) => onGroupAction(group, action)}
          />
        )
        return (
          <ChipRow key={group.name} labelledBy={id} quiet={quiet} head={head}>
            {group.entities.map((entity) => chip(entity, group.name, false))}
          </ChipRow>
        )
      })}
      <PausedList paused={layout.paused} chip={({ entity, group }) => chip(entity, group, true)} />
    </section>
  )
}
