// SuggestionList: the checklist of things worth following. The label is in normal weight, the
// reason in small muted text, and what is already followed (or just followed) is shown disabled.
import { useId } from 'react'
import type { TrackSuggestion } from '../api/types'
import { KIND_LABELS, suggestionKey } from './followLogic'

export type RowStatus = 'idle' | 'following' | 'done' | 'failed' | 'existing'

export interface RowState {
  status: RowStatus
  error?: string
}

export interface SuggestionListProps {
  suggestions: readonly TrackSuggestion[]
  ticked: ReadonlySet<string>
  rows: Readonly<Record<string, RowState>>
  disabled: boolean
  onToggle: (key: string) => void
}

/** Words shown at the right of a row that cannot be ticked. */
function lockedNote(suggestion: TrackSuggestion, row: RowState | undefined): string | null {
  if (row?.status === 'done') return 'Following'
  if (suggestion.already_followed || row?.status === 'existing') return 'Already following'
  if (row?.status === 'following') return 'Following…'
  return null
}

/** One checkbox per suggestion inside a labelled group. */
export function SuggestionList({ suggestions, ticked, rows, disabled, onToggle }: SuggestionListProps) {
  const base = useId()
  return (
    <fieldset className="rf-list">
      <legend className="r-sr-only">What to follow</legend>
      {suggestions.map((suggestion, index) => {
        const key = suggestionKey(suggestion)
        const row = rows[key]
        const note = lockedNote(suggestion, row)
        const locked = note !== null && note !== 'Following…'
        const inputId = `${base}-i${index}`
        const whyId = `${base}-w${index}`
        return (
          <div key={key} className="rf-option">
            <input
              id={inputId}
              type="checkbox"
              className="rf-option__box"
              checked={locked || ticked.has(key)}
              disabled={locked || disabled}
              aria-describedby={whyId}
              onChange={() => onToggle(key)}
            />
            <div className="rf-option__body">
              <div className="rf-option__line">
                <label className="rf-option__label" htmlFor={inputId}>
                  {suggestion.label}
                </label>
                <span className="rf-kind">{KIND_LABELS[suggestion.kind]}</span>
                {note && <span className="rf-option__note">{note}</span>}
              </div>
              <p id={whyId} className="rf-option__why">
                {suggestion.why}
              </p>
              {row?.status === 'failed' && row.error && (
                <p className="r-error-text rf-option__error" role="alert">
                  {row.error}
                </p>
              )}
            </div>
          </div>
        )
      })}
    </fieldset>
  )
}
