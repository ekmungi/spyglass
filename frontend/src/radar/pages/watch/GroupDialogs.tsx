// GroupDialogs: the small dialogs behind a group's menu: rename, move all to another group, and
// the confirmation before removing a group.
import { useId, useState, type FormEvent } from 'react'
import { Button, Dialog, Select } from '../../ui'

/** The longest group name the service accepts. */
export const MAX_GROUP_NAME = 60
const NEW_GROUP = '__new__'

export type GroupDialogState = { kind: 'rename' | 'move' | 'remove'; name: string; count: number } | null

export interface GroupDialogProps {
  /** The dialog to show: what it is for, the group it acts on and how many names are in it. */
  state: NonNullable<GroupDialogState>
  /** Names of the other groups, for "Move all". */
  others: string[]
  busy: boolean
  /** Problem from the last attempt, shown in the dialog. */
  problem: string | null
  onClose: () => void
  onRename: (to: string) => void
  onMove: (to: string) => void
  onRemove: () => void
}

/** The right dialog for the state's kind; mount it only while open so fields start fresh. */
export function GroupDialog({ state, others, busy, problem, onClose, onRename, onMove, onRemove }: GroupDialogProps) {
  if (state.kind === 'remove') {
    const names = `${state.count} ${state.count === 1 ? 'name' : 'names'}`
    return (
      <Dialog
        open
        onClose={onClose}
        title={`Remove ${state.name}?`}
        footer={
          <>
            <Button variant="quiet" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" disabled={busy} onClick={onRemove}>
              Remove group
            </Button>
          </>
        }
      >
        <p className="r-meta">
          This stops checking all {names} in this group and forgets which items mention them. The items stay in your Feed. You can undo it right after.
        </p>
        {problem && <p className="r-error-text" role="alert">{problem}</p>}
      </Dialog>
    )
  }
  return <NameDialog state={state} others={others} busy={busy} problem={problem} onClose={onClose} onSubmit={state.kind === 'rename' ? onRename : onMove} />
}

interface NameDialogProps {
  state: NonNullable<GroupDialogState>
  others: string[]
  busy: boolean
  problem: string | null
  onClose: () => void
  onSubmit: (to: string) => void
}

/** Rename (one text field) or move (pick a group or type a new one). */
function NameDialog({ state, others, busy, problem, onClose, onSubmit }: NameDialogProps) {
  const moving = state.kind === 'move'
  const [choice, setChoice] = useState(others[0] ?? NEW_GROUP)
  const [typed, setTyped] = useState(moving ? '' : state.name)
  const [error, setError] = useState<string | null>(null)
  const formId = useId()
  const inputId = useId()
  const typing = !moving || choice === NEW_GROUP

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const to = (typing ? typed : choice).trim()
    if (!to) return setError('Give the group a name.')
    if (to.length > MAX_GROUP_NAME) return setError(`A group name can be at most ${MAX_GROUP_NAME} characters.`)
    setError(null)
    onSubmit(to)
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={moving ? `Move all of ${state.name}` : `Rename ${state.name}`}
      footer={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form={formId} disabled={busy}>
            {moving ? 'Move' : 'Rename'}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} noValidate>
        {moving && (
          <div className="r-field">
            <Select
              label="Move to"
              value={choice}
              onChange={setChoice}
              options={[...others.map((name) => ({ value: name, label: name })), { value: NEW_GROUP, label: 'A new group…' }]}
            />
          </div>
        )}
        {typing && (
          <div className="r-field">
            <label htmlFor={inputId}>{moving ? 'New group name' : 'Group name'}</label>
            <input id={inputId} className="r-input" value={typed} maxLength={MAX_GROUP_NAME} autoFocus onChange={(event) => setTyped(event.target.value)} />
          </div>
        )}
        {(error ?? problem) && (
          <p className="r-error-text" role="alert">
            {error ?? problem}
          </p>
        )}
      </form>
    </Dialog>
  )
}
