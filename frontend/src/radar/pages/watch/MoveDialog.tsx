// MoveDialog: move one watched name to another existing group, chosen from a short list. A refusal
// from the service is shown inside the dialog, which stays open.
import { useState } from 'react'
import { errorMessage } from '../../api/errors'
import { Button, Dialog } from '../../ui'
import type { WatchEntry } from './api'

export interface MoveDialogProps {
  entry: WatchEntry
  /** The name of the group the entry is shown in now. */
  from: string
  /** The other groups, in page order; the first is chosen at the start. */
  others: string[]
  onClose: () => void
  /** Move the entry; rejects with the service's plain-language message on failure. */
  onMove: (to: string) => Promise<void>
}

/** A radio list of the other groups and a Move button; mount it only while open so it starts fresh. */
export function MoveDialog({ entry, from, others, onClose, onMove }: MoveDialogProps) {
  const [choice, setChoice] = useState(others[0] ?? '')
  const [moving, setMoving] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const move = async () => {
    if (!choice) return
    setMoving(true)
    setProblem(null)
    try {
      await onMove(choice)
    } catch (cause) {
      setProblem(errorMessage(cause))
      setMoving(false)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Move ${entry.name}`}
      footer={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={moving || !choice} onClick={() => void move()}>
            Move
          </Button>
        </>
      }
    >
      <p className="r-meta">Now in {from}.</p>
      {others.length > 0 ? (
        <fieldset className="rw-radios">
          <legend className="r-sr-only">Move to</legend>
          {others.map((name) => (
            <label key={name} className="rw-radio">
              <input type="radio" name="rw-move-to" value={name} checked={choice === name} onChange={() => setChoice(name)} />
              {name}
            </label>
          ))}
        </fieldset>
      ) : (
        <p className="r-meta">There is no other group yet. Use Details to type a new group name.</p>
      )}
      {problem && (
        <p className="r-error-text" role="alert">
          {problem}
        </p>
      )}
    </Dialog>
  )
}
