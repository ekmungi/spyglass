// FollowPane: the Add dialog's "Follow a topic" step: a name, the phrase to search for, and the section it belongs to.
import { useId, useState, type FormEvent } from 'react'
import { errorMessage } from '../../api/errors'
import { DEFAULT_SECTIONS } from '../../lib/sections'
import { Button, Select } from '../../ui'

export interface FollowFields {
  label: string
  query: string
  section: string
}

export interface FollowPaneProps {
  /** Follow the topic; rejects with a readable message on failure. */
  onFollow: (fields: FollowFields) => Promise<void>
  onBack: () => void
}

const SECTIONS = DEFAULT_SECTIONS.map((section) => ({ value: section.key, label: section.label }))

/** A small form. The search phrase falls back to the name when left empty. */
export function FollowPane({ onFollow, onBack }: FollowPaneProps) {
  const [label, setLabel] = useState('')
  const [query, setQuery] = useState('')
  const [section, setSection] = useState(SECTIONS[0]?.value ?? '')
  const [problem, setProblem] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const labelId = useId()
  const queryId = useId()

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const name = label.trim()
    if (!name) {
      setProblem('Give the topic a name first.')
      return
    }
    setSaving(true)
    setProblem(null)
    try {
      await onFollow({ label: name, query: query.trim() || name, section })
    } catch (cause) {
      setProblem(errorMessage(cause))
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <p className="r-meta rw-pane-lead">Spyglass searches the news for this subject every day and puts what it finds in your Feed.</p>
      <div className="r-field">
        <label htmlFor={labelId}>Name</label>
        <input
          id={labelId}
          className="r-input"
          value={label}
          autoFocus
          placeholder="For example protein structure prediction"
          onChange={(event) => setLabel(event.target.value)}
        />
      </div>
      <div className="r-field">
        <label htmlFor={queryId}>Search phrase</label>
        <input
          id={queryId}
          className="r-input"
          value={query}
          placeholder="Leave empty to search for the name"
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="r-field">
        <Select label="Section" value={section} onChange={setSection} options={SECTIONS} />
      </div>
      {problem && (
        <p className="r-error-text" role="alert">
          {problem}
        </p>
      )}
      <div className="r-dialog__footer">
        <Button variant="quiet" onClick={onBack} disabled={saving}>
          Back
        </Button>
        <Button variant="primary" type="submit" disabled={saving}>
          Follow
        </Button>
      </div>
    </form>
  )
}
