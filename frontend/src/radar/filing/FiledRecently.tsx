// FiledRecently: what was filed in the last 14 days, newest first, each with its note's place and a
// way to open the note in Obsidian. A note a background run placed by its own best guess says so.
import { useId, useState } from 'react'
import { openFiledNote } from '../api/client'
import { errorMessage } from '../api/errors'
import type { FilingRecent } from '../api/types'
import { ItemLink } from '../components/ItemLink'
import { Button, Pill, SectionHeading, toast } from '../ui'
import { NoteName, NotePath } from './NotePath'
import { splitNotePath } from './notePathText'

/** How many rows show before "Show all". */
const FIRST_ROWS = 5

/** The Filed recently group of the To file view; nothing when nothing was filed. */
export function FiledRecently({ rows }: { rows: FilingRecent[] }) {
  const [all, setAll] = useState(false)
  const headingId = useId()
  if (!rows.length) return null
  const shown = all ? rows : rows.slice(0, FIRST_ROWS)

  const open = async (row: FilingRecent) => {
    try {
      await openFiledNote(row.item_id)
    } catch (cause) {
      toast(`Could not open the note. ${errorMessage(cause)}`, { tone: 'error' })
    }
  }

  return (
    <section className="r-filing__group r-filing__group--recent r-appear" aria-labelledby={headingId}>
      <SectionHeading id={headingId} note="Last 14 days">
        Filed recently
      </SectionHeading>
      <ul className="r-rows r-filing__recent-list">
        {shown.map((row) => {
          const { folders, name } = splitNotePath(row.path)
          return (
          <li key={`${row.item_id}-${row.at}`} className="r-filing__recent">
            <ItemLink id={row.item_id} className="r-filing__headline">
              {row.headline}
            </ItemLink>
            <span className="r-meta r-filing__path">
              <NotePath path={folders.join('/')} />
              <NoteName name={name} />
              {row.project && <Pill tone="neutral">{row.project}</Pill>}
              {row.best_guess && <Pill tone="muted">placed by best guess</Pill>}
            </span>
            <Button variant="quiet" size="sm" aria-label={`Open ${row.headline} in Obsidian`} onClick={() => void open(row)}>
              Open in Obsidian
            </Button>
          </li>
          )
        })}
      </ul>
      {rows.length > FIRST_ROWS && (
        <Button variant="quiet" size="sm" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${rows.length}`}
        </Button>
      )}
    </section>
  )
}
