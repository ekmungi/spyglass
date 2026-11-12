// AvoidEditor: things to leave out of the brief; add and remove.
import { useId, useState, type FormEvent } from 'react'
import { Button } from '../../ui'

export interface AvoidEditorProps {
  items: readonly string[]
  errors: Record<number, string>
  onChange: (index: number, value: string) => void
  onRemove: (index: number) => void
  onAdd: (value: string) => void
}

/** Editable lines with Remove, then one line to add a new subject to avoid. */
export function AvoidEditor({ items, errors, onChange, onRemove, onAdd }: AvoidEditorProps) {
  const base = useId()
  const [text, setText] = useState('')
  const [problem, setProblem] = useState<string | null>(null)

  const add = (event: FormEvent) => {
    event.preventDefault()
    const value = text.trim()
    if (!value) {
      setProblem('Write what to leave out first.')
      return
    }
    if (items.some((entry) => entry.trim().toLowerCase() === value.toLowerCase())) {
      setProblem('This is already in the list.')
      return
    }
    onAdd(value)
    setText('')
    setProblem(null)
  }

  return (
    <div>
      {items.length === 0 && <p className="r-meta rpr-empty">Nothing to avoid yet. Add subjects you never want to see.</p>}
      <ul className="r-rows">
        {items.map((entry, index) => (
          <li key={index} className="rpr-row">
            <div className="rpr-topic">
              <div className="rpr-topic__name">
                <label htmlFor={`${base}-${index}`} className="r-sr-only">
                  Leave out {index + 1}
                </label>
                <input
                  id={`${base}-${index}`}
                  className="r-input"
                  value={entry}
                  aria-invalid={errors[index] ? true : undefined}
                  aria-describedby={errors[index] ? `${base}-${index}-error` : undefined}
                  onChange={(event) => onChange(index, event.target.value)}
                />
                {errors[index] && (
                  <span id={`${base}-${index}-error`} className="r-error-text">
                    {errors[index]}
                  </span>
                )}
              </div>
              <Button variant="quiet" size="sm" aria-label={`Remove ${entry || `line ${index + 1}`} from the leave-out list`} onClick={() => onRemove(index)}>
                Remove
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <form className="rpr-add" onSubmit={add} noValidate>
        <div className="rpr-topic rpr-topic--avoid">
          <div className="rpr-topic__name">
            <label htmlFor={`${base}-new`} className="r-sr-only">
              New subject to leave out
            </label>
            <input id={`${base}-new`} className="r-input" value={text} placeholder="Add something to leave out" onChange={(event) => setText(event.target.value)} />
          </div>
          <Button type="submit" variant="secondary" size="sm">
            Add
          </Button>
        </div>
        {problem && <span className="r-error-text">{problem}</span>}
      </form>
    </div>
  )
}
