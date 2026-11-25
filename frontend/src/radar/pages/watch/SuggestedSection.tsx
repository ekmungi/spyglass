// SuggestedSection: "Suggested this month": one row of suggestion chips per profile section that has
// any, then one per topic search and the Other row, the number still undecided, and "Hide the rest for
// good". It draws the rows it is given; the page decides when they change.
import type { SuggestionStatus, WatchStatus } from '../../api/types'
import { Button, SectionHeading } from '../../ui'
import type { WatchEntry } from './api'
import { ChipRow } from './ChipRow'
import type { SuggestionRow } from './organize'
import { SuggestionChip } from './SuggestionChip'
import { decidedText, hiddenText } from './suggestionText'

export interface SuggestedSectionProps {
  /** The suggestion rows as laid out at load, with the looks changed since. */
  rows: SuggestionRow[]
  /** Names whose change is on the way to the server. */
  busyIds: ReadonlySet<number>
  /** Give one name a new status in place, with the toast to show after it. */
  change: (entity: WatchEntry, to: WatchStatus, done: string) => void
  /** Give many names the same suggestion status in one request. */
  changeMany: (entities: readonly WatchEntry[], to: SuggestionStatus, done: (count: number) => string) => void
}

/** "3 undecided · 2 now watched, in their group on your next visit", counting the looks as they are now. */
function countLine(names: readonly WatchEntry[]): string {
  const open = names.filter((entity) => entity.status === 'suggested').length
  const picked = names.filter((entity) => entity.status === 'active').length
  return `${open} undecided${picked > 0 ? ` · ${picked} now watched, in their group on your next visit` : ''}`
}

/** A row's heading: the profile section, or the topic search with how long its names are kept. */
function RowHeading({ id, row }: { id: string; row: SuggestionRow }) {
  return (
    <>
      <div className="rw-group__title">
        <h3 className="rw-group__name" id={id}>
          {row.topic ? `From your search: ${row.label}` : row.label}
        </h3>
      </div>
      {row.topic && <div className="rw-group__meta">kept for 30 days</div>}
    </>
  )
}

/** The section, or nothing when no row holds a suggestion. */
export function SuggestedSection({ rows, busyIds, change, changeMany }: SuggestedSectionProps) {
  const shown = rows.filter((row) => row.entities.length > 0)
  if (shown.length === 0) return null
  const names = shown.flatMap((row) => row.entities)
  const undecided = names.filter((entity) => entity.status === 'suggested' && !busyIds.has(entity.id))
  return (
    <section aria-labelledby="watch-suggested" className="rw-section">
      <SectionHeading id="watch-suggested" note="up to 5 per section of your profile">
        Suggested this month
      </SectionHeading>
      <p className="rw-lead">
        Organisations named most often in your top and notable items over the last 30 days. Click a name to watch it, or the cross if it is not
        of interest.
      </p>
      {shown.map((row, index) => {
        const id = `watch-suggest-${index}`
        return (
          <ChipRow key={row.key} labelledBy={id} head={<RowHeading id={id} row={row} />}>
            {row.entities.map((entity) => (
              <SuggestionChip key={entity.id} entity={entity} busy={busyIds.has(entity.id)} onChange={(to) => change(entity, to, decidedText(entity, to))} />
            ))}
          </ChipRow>
        )
      })}
      <div className="rw-foot">
        <span className="r-meta">{countLine(names)}</span>
        <Button variant="quiet" size="sm" disabled={undecided.length === 0} onClick={() => changeMany(undecided, 'rejected', hiddenText)}>
          Hide the rest for good
        </Button>
      </div>
    </section>
  )
}
