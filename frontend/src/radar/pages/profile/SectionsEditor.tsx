// SectionsEditor: the brief's sections. The key is fixed (shown small); the name and description are editable.
import { useId } from 'react'
import type { ProfileSection } from '../../api/types'
import type { ProfileErrors } from './validate'

export interface SectionsEditorProps {
  sections: readonly ProfileSection[]
  errors: ProfileErrors['sections']
  onChange: (index: number, patch: Partial<ProfileSection>) => void
}

/** One row per section: a name field, a description field, and the fixed key in small type. */
export function SectionsEditor({ sections, errors, onChange }: SectionsEditorProps) {
  const base = useId()
  return (
    <ul className="r-rows">
      {sections.map((section, index) => {
        const problem = errors[index] ?? {}
        const labelId = `${base}-label-${index}`
        const descId = `${base}-desc-${index}`
        return (
          <li key={section.key} className="rpr-row rpr-row--stack">
            <div className="rpr-grid">
              <div className="r-field">
                <label htmlFor={labelId}>
                  Section name
                </label>
                <input
                  id={labelId}
                  className="r-input"
                  value={section.label}
                  aria-invalid={problem.label ? true : undefined}
                  aria-describedby={problem.label ? `${labelId}-error` : undefined}
                  onChange={(event) => onChange(index, { label: event.target.value })}
                />
                {problem.label && (
                  <span id={`${labelId}-error`} className="r-error-text">
                    {problem.label}
                  </span>
                )}
              </div>
              <div className="r-field">
                <label htmlFor={descId}>What belongs here</label>
                <textarea
                  id={descId}
                  className="r-textarea"
                  rows={2}
                  value={section.description}
                  aria-invalid={problem.description ? true : undefined}
                  aria-describedby={problem.description ? `${descId}-error` : undefined}
                  onChange={(event) => onChange(index, { description: event.target.value })}
                />
                {problem.description && (
                  <span id={`${descId}-error`} className="r-error-text">
                    {problem.description}
                  </span>
                )}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
