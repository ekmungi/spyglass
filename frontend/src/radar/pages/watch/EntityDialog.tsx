// EntityDialog: edit a name that is already in the Watch register (adding is in the Add dialog).
import { useId, useState } from 'react'
import { Button, Dialog } from '../../ui'
import type { EntryFields, WatchEntry } from './api'
import { EntityForm } from './EntityForm'

export interface EntityDialogProps {
  open: boolean
  /** The entry being edited. */
  entry: WatchEntry
  /** Group names already in use, offered as suggestions. */
  categories: string[]
  onClose: () => void
  /** Save the fields; rejects with the server's plain-language message on failure. */
  onSave: (fields: EntryFields) => Promise<void>
}

/** A small form dialog; the parent keys it by entry so fields start clean. */
export function EntityDialog({ open, entry, categories, onClose, onSave }: EntityDialogProps) {
  const [saving, setSaving] = useState(false)
  const formId = useId()
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Edit ${entry.name}`}
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
      <EntityForm entry={entry} categories={categories} formId={formId} onSave={onSave} onSavingChange={setSaving} />
    </Dialog>
  )
}
