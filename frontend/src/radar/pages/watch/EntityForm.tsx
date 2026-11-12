// EntityForm: the fields for one register entry (name, kind, group, search query), shared by the
// Add dialog's "Add one organisation" step and the Edit dialog. The parent supplies the submit button.
import { useId, useState, type FormEvent } from 'react'
import { errorMessage } from '../../api/errors'
import { Select } from '../../ui'
import type { EntryFields, WatchEntry } from './api'

const KINDS = [
  { value: 'company', label: 'Company' },
  { value: 'lab', label: 'Lab' },
  { value: 'regulator', label: 'Regulator' },
  { value: 'person', label: 'Person' },
  { value: 'publication', label: 'Publication' },
]

export interface EntityFormProps {
  /** The entry being edited, or null to add a new one. */
  entry: WatchEntry | null
  /** Group names already in use, offered as suggestions. */
  categories: string[]
  /** The id the parent's submit button points at with its `form` attribute. */
  formId: string
  /** Save the fields; rejects with the server's plain-language message on failure. */
  onSave: (fields: EntryFields) => Promise<void>
  /** Told when saving starts and ends, so the parent can disable its submit button. */
  onSavingChange?: (saving: boolean) => void
}

/** The form body; it remounts for each entry (the parent keys it) so fields start clean. */
export function EntityForm({ entry, categories, formId, onSave, onSavingChange }: EntityFormProps) {
  const [name, setName] = useState(entry?.name ?? '')
  const [kind, setKind] = useState(entry?.kind ?? 'company')
  const [category, setCategory] = useState(entry?.category ?? '')
  const [query, setQuery] = useState(entry?.query ?? '')
  const [problem, setProblem] = useState<string | null>(null)
  const nameId = useId()
  const categoryId = useId()
  const queryId = useId()
  const listId = useId()

  const submit = async (event?: FormEvent) => {
    event?.preventDefault()
    if (!name.trim()) {
      setProblem('Give it a name first.')
      return
    }
    onSavingChange?.(true)
    setProblem(null)
    try {
      await onSave({ name: name.trim(), kind, category: category.trim(), query: query.trim() || null })
    } catch (cause) {
      setProblem(errorMessage(cause))
      onSavingChange?.(false)
    }
  }

  return (
    <form id={formId} onSubmit={submit} noValidate>
      <div className="r-field">
        <label htmlFor={nameId}>Name</label>
        <input id={nameId} className="r-input" value={name} onChange={(event) => setName(event.target.value)} required autoFocus />
      </div>
      <div className="r-field">
        <Select label="Kind" value={kind} onChange={setKind} options={KINDS} />
      </div>
      <div className="r-field">
        <label htmlFor={categoryId}>Group</label>
        <input
          id={categoryId}
          className="r-input"
          list={listId}
          value={category}
          maxLength={60}
          placeholder="For example AI labs or Regulators"
          onChange={(event) => setCategory(event.target.value)}
        />
        <datalist id={listId}>
          {categories.map((option) => (
            <option key={option} value={option} />
          ))}
        </datalist>
      </div>
      <div className="r-field">
        <label htmlFor={queryId}>Search query</label>
        <input
          id={queryId}
          className="r-input"
          value={query}
          placeholder="Leave empty to search for the name"
          onChange={(event) => setQuery(event.target.value)}
        />
        <span className="r-meta">What Spyglass searches the news for each day.</span>
      </div>
      {problem && (
        <p className="r-error-text" role="alert">
          {problem}
        </p>
      )}
    </form>
  )
}
