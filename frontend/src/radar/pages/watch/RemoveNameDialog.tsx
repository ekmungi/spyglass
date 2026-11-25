// RemoveNameDialog: the question before one watched name is removed, with the hint that one click on
// the chip pauses the name instead and keeps it.
import { Button, Dialog } from '../../ui'

export interface RemoveNameDialogProps {
  open: boolean
  /** The name being removed, or null while the dialog is closed. */
  name: string | null
  busy: boolean
  onClose: () => void
  onRemove: () => void
}

/** Stays mounted so it can play its exit; `open` shows it. */
export function RemoveNameDialog({ open, name, busy, onClose, onRemove }: RemoveNameDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={name ? `Remove ${name}?` : 'Remove'}
      footer={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={busy} onClick={onRemove}>
            Remove
          </Button>
        </>
      }
    >
      <p className="r-meta">Spyglass stops checking this name and forgets which items mention it. The items themselves stay in your feed.</p>
      <p className="r-meta">To stop the searches and keep the name, close this and click the name once: it turns grey.</p>
    </Dialog>
  )
}
