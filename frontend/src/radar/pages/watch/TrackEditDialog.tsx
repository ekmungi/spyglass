// TrackEditDialog: change a followed topic's name, the search query run for it, and its section.
import { useId, useState, type FormEvent } from 'react'
import type { Track } from '../../api/types'
import { errorMessage } from '../../api/errors'
import { DEFAULT_SECTIONS } from '../../lib/sections'
import { Button, Dialog, Select } from '../../ui'

export interface TrackFields {
  label: string
  query: string
  section: string
}

export interface TrackEditDialogProps {
  track: Track
  onClose: () => void
  /** Save the fields; rejects with a readable message on failure. */
  onSave: (fields: TrackFields) => Promise<void>
}

/** A small form; the parent keys it by track so the fields start from the track's values. */
export function TrackEditDialog({ track, onClose, onSave }: TrackEditDialogProps) {
  const [label, setLabel] = useState(track.label)
  const [query, setQuery] = useState(track.query)
  const [section, setSection] = useState(track.section)
  const [problem, setProblem] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const labelId = useId()
  const queryId = useId()
  const formId = useId()
  const known = DEFAULT_SECTIONS.map((entry) => ({ value: entry.key, label: entry.label }))
  // A track can carry a section the profile no longer lists; keep it selectable so saving does not move it.
  const sections = known.some((entry) => entry.value === track.section)
    ? known
    : [{ value: track.section, label: track.section_label || track.section }, ...known]

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!label.trim() || !query.trim()) {
      setProblem('A topic needs a name and a search query.')
      return
    }
    setSaving(true)
    setProblem(null)
    try {
      await onSave({ label: label.trim(), query: query.trim(), section })
    } catch (cause) {
      setProblem(errorMessage(cause))
      setSaving(false)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Edit ${track.label}`}
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
      <form id={formId} onSubmit={submit} noValidate>
        <div className="r-field">
          <label htmlFor={labelId}>Name</label>
          <input id={labelId} className="r-input" value={label} onChange={(event) => setLabel(event.target.value)} />
        </div>
        <div className="r-field">
          <label htmlFor={queryId}>Search query</label>
          <input id={queryId} className="r-input" value={query} onChange={(event) => setQuery(event.target.value)} />
          <span className="r-meta">What Spyglass searches the news for each day.</span>
        </div>
        <div className="r-field">
          <Select label="Section" value={section} onChange={setSection} options={sections} />
        </div>
        {problem && (
          <p className="r-error-text" role="alert">
            {problem}
          </p>
        )}
      </form>
    </Dialog>
  )
}
