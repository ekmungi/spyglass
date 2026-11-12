// Switch: an on/off toggle (role="switch") used for feeds and for the local command-line engines.
import './switch.css'

export interface SwitchProps {
  /** Accessible name, e.g. "Hacker News feed". */
  label: string
  checked: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
}

/** A small keyboard-accessible switch; Space or Enter toggles it, and `label` names it for screen readers. */
export function Switch({ label, checked, onChange, disabled }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className="rp-switch"
      onClick={() => onChange(!checked)}
    >
      <span className="rp-switch__knob" aria-hidden="true" />
    </button>
  )
}
