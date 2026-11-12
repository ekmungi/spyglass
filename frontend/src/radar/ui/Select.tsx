// Select: a styled native select (accessible by default), with optional option groups.
import { useId } from 'react'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface SelectGroup {
  label: string
  options: SelectOption[]
}

export interface SelectProps {
  label: string
  value: string
  onChange: (value: string) => void
  options?: SelectOption[]
  groups?: SelectGroup[]
  hideLabel?: boolean
  disabled?: boolean
  className?: string
}

/** A labelled native select; pass `options`, `groups`, or both (plain options render first). */
export function Select({ label, value, onChange, options = [], groups = [], hideLabel, disabled, className }: SelectProps) {
  const id = useId()
  return (
    <span className={['r-select', className ?? ''].filter(Boolean).join(' ')}>
      <label htmlFor={id} className={hideLabel ? 'r-sr-only' : undefined}>
        {label}
      </label>
      <select id={id} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
        {groups.map((group) => (
          <optgroup key={group.label} label={group.label}>
            {group.options.map((option) => (
              <option key={option.value} value={option.value} disabled={option.disabled}>
                {option.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </span>
  )
}
