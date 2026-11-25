// SuggestionChip: one suggested organisation as a chip with the number of items that named it. A click
// on the name watches it (green) and a second click undoes that; the cross marks it not of interest
// (struck through), and a click on a struck chip takes it back. The chip never moves when it changes.
import type { WatchStatus } from '../../api/types'
import { Chip, IconButton, IconClose, IconUndo, Tooltip } from '../../ui'
import type { WatchEntry } from './api'
import { spokenName, tipText } from './suggestionText'

export interface SuggestionChipProps {
  /** The suggestion as it looks now: "suggested" open, "active" watched on this visit, "rejected" struck through. */
  entity: WatchEntry
  /** Its change is on the way to the server; a click is ignored until it is back. */
  busy: boolean
  /** Ask for the name's next status. */
  onChange: (to: WatchStatus) => void
}

/** The outer pill's class for each look. */
const LOOK_CLASS: Partial<Record<WatchStatus, string>> = { active: 'rw-chip--on', rejected: 'rw-chip--rej' }

/** The toggle button (aria-pressed when watched) and the cross or take-back button, in one rounded chip. */
export function SuggestionChip({ entity, busy, onChange }: SuggestionChipProps) {
  const look = entity.status
  const ask = (to: WatchStatus) => {
    if (!busy) onChange(to)
  }
  return (
    <Tooltip label={tipText(entity)}>
      <span className={`rw-chip ${LOOK_CLASS[look] ?? 'rw-chip--sug'}`} aria-busy={busy || undefined}>
        <Chip
          selected={look === 'active'}
          className="rw-chip__main"
          aria-label={spokenName(entity)}
          aria-disabled={busy || undefined}
          count={entity.count > 0 ? entity.count : undefined}
          onClick={() => ask(look === 'suggested' ? 'active' : 'suggested')}
        >
          {look === 'active' ? (
            <span className="rw-dot" aria-hidden="true" />
          ) : (
            <span className="rw-chip__plus" aria-hidden="true">
              {look === 'suggested' ? '+' : ''}
            </span>
          )}
          <span className="rw-chip__name">{entity.name}</span>
        </Chip>
        {look === 'suggested' && (
          <IconButton
            className="rw-chip__x"
            label={`Not of interest: ${entity.name}`}
            icon={<IconClose size={14} />}
            size="sm"
            tooltip={false}
            aria-disabled={busy || undefined}
            onClick={() => ask('rejected')}
          />
        )}
        {look === 'rejected' && (
          <IconButton
            className="rw-chip__x"
            label={`Take back ${entity.name}`}
            icon={<IconUndo size={14} />}
            size="sm"
            tooltip={false}
            aria-disabled={busy || undefined}
            onClick={() => ask('suggested')}
          />
        )}
        {/* A watched chip keeps the room of its cross, so its width does not change under the cursor. */}
        {look === 'active' && <span className="rw-chip__x" aria-hidden="true" />}
      </span>
    </Tooltip>
  )
}
