// WatchChip: one followed name as a chip. A click switches it between watched (green, pressed) and
// paused (grey); the dots beside it open the rare actions. The chip never moves when it switches.
import { Chip, IconButton, IconMore, Menu, type MenuItem } from '../../ui'
import type { WatchEntry } from './api'

export interface WatchChipProps {
  /** The name as it looks now: "active" shows it watched, anything else paused. */
  entity: WatchEntry
  /** The group's name, shown after the name in the Paused list, where the chip is not under its group. */
  group?: string
  /** Its change is on the way to the server; a click is ignored until it is back. */
  busy: boolean
  menu: MenuItem[]
  onToggle: () => void
}

/** The toggle button (aria-pressed) and the menu button, held together in one rounded chip. */
export function WatchChip({ entity, group, busy, menu, onToggle }: WatchChipProps) {
  const watched = entity.status === 'active'
  const more = `More actions for ${entity.name}`
  return (
    <span className={`rw-chip ${watched ? 'rw-chip--on' : 'rw-chip--off'}`} aria-busy={busy || undefined}>
      <Chip
        selected={watched}
        className="rw-chip__main"
        // Spoken as "FDA, in Regulators" where the group is shown beside the name.
        aria-label={group ? `${entity.name}, in ${group}` : undefined}
        aria-disabled={busy || undefined}
        onClick={() => {
          if (!busy) onToggle()
        }}
      >
        <span className="rw-dot" aria-hidden="true" />
        <span className="rw-chip__name">{entity.name}</span>
        {group && <span className="rw-chip__group">{group}</span>}
      </Chip>
      <Menu
        label={more}
        align="start"
        items={menu}
        trigger={<IconButton className="rw-chip__more" label={more} icon={<IconMore size={14} />} size="sm" tooltip={false} />}
      />
    </span>
  )
}
