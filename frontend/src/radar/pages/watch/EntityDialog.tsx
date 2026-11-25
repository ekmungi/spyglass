// EntityDialog: the details of a name that is already in the Watch register (what it is, why it is
// followed, its latest items) above the form that edits it. Adding is in the Add dialog.
import { useId, useState } from 'react'
import { ItemLink } from '../../components/ItemLink'
import { plainText } from '../../lib/plainText'
import { Button, Dialog } from '../../ui'
import { formatDay } from '../sources/format'
import type { EntryFields, WatchEntry } from './api'
import { EntityForm } from './EntityForm'
import { kindLabel } from './kind'

/** How many of the latest items the dialog lists. */
const LATEST = 3

export interface EntityDialogProps {
  open: boolean
  /** The entry, with the status it shows on the page now. */
  entry: WatchEntry
  /** The name of the group it is shown in. */
  group: string
  /** Group names already in use, offered as suggestions. */
  categories: string[]
  onClose: () => void
  /** Save the fields; rejects with the server's plain-language message on failure. */
  onSave: (fields: EntryFields) => Promise<void>
}

/** "Company · Imaging AI · watched · last found 23 Nov": what it is, where, and whether it is watched. */
function summaryLine(entry: WatchEntry, group: string): string {
  const parts = [kindLabel(entry.kind), group, entry.status === 'active' ? 'watched' : 'paused']
  const last = formatDay(entry.last_hit_at)
  if (last) parts.push(`last found ${last}`)
  return parts.join(' · ')
}

/** What the name is and what it brought in, read-only. */
function EntityDetails({ entry, group }: { entry: WatchEntry; group: string }) {
  const latest = (entry.recent ?? []).slice(0, LATEST)
  return (
    <div className="rw-details">
      <p className="r-meta">{summaryLine(entry, group)}</p>
      {entry.why && <p className="rw-why">{entry.why}</p>}
      {entry.aliases.length > 0 && (
        <div>
          <h3 className="rw-details__label">Also matched as</h3>
          <p className="rw-details__text">{entry.aliases.join(', ')}</p>
        </div>
      )}
      <div>
        <h3 className="rw-details__label">Latest items</h3>
        {latest.length > 0 ? (
          <ul className="rw-recent" aria-label={`Latest from ${entry.name}`}>
            {latest.map((item) => (
              <li key={item.id}>
                <ItemLink id={item.id}>{plainText(item.headline) || plainText(item.title)}</ItemLink>
                {(item.published_at || item.fetched_at) && <span className="r-meta"> {formatDay(item.published_at ?? item.fetched_at)}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="r-meta">No items mention it yet.</p>
        )}
      </div>
    </div>
  )
}

/** The details, then the edit form; the parent keys it by entry so the fields start clean. */
export function EntityDialog({ open, entry, group, categories, onClose, onSave }: EntityDialogProps) {
  const [saving, setSaving] = useState(false)
  const formId = useId()
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={entry.name}
      footer={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form={formId} disabled={saving}>
            Save changes
          </Button>
        </>
      }
    >
      <EntityDetails entry={entry} group={group} />
      <EntityForm entry={entry} categories={categories} formId={formId} onSave={onSave} onSavingChange={setSaving} />
    </Dialog>
  )
}
