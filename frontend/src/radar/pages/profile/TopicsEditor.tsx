// TopicsEditor: the topics the reader follows, each tied to a section; add and remove.
import { useId, useState, type FormEvent } from 'react'
import type { ProfileSection, ProfileTopic } from '../../api/types'
import { Button, Select } from '../../ui'
import type { ProfileErrors } from './validate'

export interface TopicsEditorProps {
  topics: readonly ProfileTopic[]
  sections: readonly ProfileSection[]
  errors: ProfileErrors['topics']
  onChange: (index: number, patch: Partial<ProfileTopic>) => void
  onRemove: (index: number) => void
  onAdd: (topic: ProfileTopic) => void
}

/** Rows of name plus section select with a Remove button, then one line to add a topic. */
export function TopicsEditor({ topics, sections, errors, onChange, onRemove, onAdd }: TopicsEditorProps) {
  const base = useId()
  const [name, setName] = useState('')
  const [section, setSection] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const options = [{ value: '', label: 'No section' }, ...sections.map((entry) => ({ value: entry.key, label: entry.label || entry.key }))]

  const add = (event: FormEvent) => {
    event.preventDefault()
    const text = name.trim()
    if (!text) {
      setProblem('Type a topic first.')
      return
    }
    if (topics.some((topic) => topic.name.trim().toLowerCase() === text.toLowerCase())) {
      setProblem('This topic is already in the list.')
      return
    }
    onAdd({ name: text, section })
    setName('')
    setProblem(null)
  }

  return (
    <div>
      {topics.length === 0 && <p className="r-meta rpr-empty">No topics yet. Add the subjects you want Spyglass to watch for.</p>}
      <ul className="r-rows">
        {topics.map((topic, index) => {
          const error = errors[index] ?? {}
          const nameId = `${base}-name-${index}`
          return (
            <li key={index} className="rpr-row">
              <div className="rpr-topic">
                <div className="rpr-topic__name">
                  <label htmlFor={nameId} className="r-sr-only">
                    Topic {index + 1}
                  </label>
                  <input
                    id={nameId}
                    className="r-input"
                    value={topic.name}
                    aria-invalid={error.name ? true : undefined}
                    aria-describedby={error.name ? `${nameId}-error` : undefined}
                    onChange={(event) => onChange(index, { name: event.target.value })}
                  />
                  {error.name && (
                    <span id={`${nameId}-error`} className="r-error-text">
                      {error.name}
                    </span>
                  )}
                </div>
                <Select
                  label={`Section for topic ${index + 1}`}
                  hideLabel
                  value={topic.section}
                  options={options}
                  onChange={(value) => onChange(index, { section: value })}
                />
                <Button variant="quiet" size="sm" aria-label={`Remove topic ${topic.name || index + 1}`} onClick={() => onRemove(index)}>
                  Remove
                </Button>
              </div>
              {error.section && <span className="r-error-text">{error.section}</span>}
            </li>
          )
        })}
      </ul>
      <form className="rpr-add" onSubmit={add} noValidate>
        <div className="rpr-topic">
          <div className="rpr-topic__name">
            <label htmlFor={`${base}-new`} className="r-sr-only">
              New topic
            </label>
            <input id={`${base}-new`} className="r-input" value={name} placeholder="Add a topic" onChange={(event) => setName(event.target.value)} />
          </div>
          <Select label="Section for the new topic" hideLabel value={section} options={options} onChange={setSection} />
          <Button type="submit" variant="secondary" size="sm">
            Add topic
          </Button>
        </div>
        {problem && <span className="r-error-text">{problem}</span>}
      </form>
    </div>
  )
}
