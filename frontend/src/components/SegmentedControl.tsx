// Segmented control: soft-rounded outer container holding flat segments;
// the active segment is a filled rounded rectangle with a subtle border.
import type { ReactNode } from 'react'

export interface SegmentOption<T extends string> {
  value: T
  label: string
  icon?: ReactNode
}

interface Props<T extends string> {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  // mini renders tighter segments for inline use (bulk relevance).
  mini?: boolean
  ariaLabel?: string
}

/** Generic segmented control matching the Claude Code desktop style. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  mini,
  ariaLabel,
}: Props<T>) {
  const pad = mini ? 'px-2.5 py-0.5' : 'px-3.5 py-1'
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex gap-0.5 border border-border bg-surface p-[3px]"
      style={{ borderRadius: 'var(--radius-card)' }}
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            className={`inline-flex items-center gap-1.5 font-semibold ${pad} ${
              active ? 'border border-border bg-card text-ink' : 'border border-transparent text-body hover:text-ink'
            }`}
            style={{
              borderRadius: 'var(--radius-control)',
              fontSize: mini ? 'var(--font-size-meta)' : 'var(--font-size-actions)',
            }}
            onClick={() => onChange(option.value)}
          >
            {option.icon}
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
