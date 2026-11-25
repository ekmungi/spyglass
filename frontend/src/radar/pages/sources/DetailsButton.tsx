// DetailsButton: the quiet "Details" / "Hide details" button at the end of a source row, which opens or
// closes the row's explanation.
import { Button } from '../../ui'

export interface DetailsButtonProps {
  open: boolean
  onToggle: () => void
  /** The id of the element that names the row, so a screen reader hears which row the button belongs to. */
  nameId: string
}

/** The toggle for one row's explanation paragraphs; the row keeps the open state. */
export function DetailsButton({ open, onToggle, nameId }: DetailsButtonProps) {
  return (
    <div className="rs-actions">
      <Button variant="quiet" size="sm" aria-expanded={open} aria-describedby={nameId} onClick={onToggle}>
        {open ? 'Hide details' : 'Details'}
      </Button>
    </div>
  )
}
