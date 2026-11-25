// Tabs: a strip of text tabs with a line under the selected one. It never wraps; a long strip
// scrolls sideways. Each tab may carry small text (a count) and a red alert mark. The selected tab is
// the caller's state: the strip only reports which tab the reader chose.
import { useRef, type KeyboardEvent } from 'react'
import { IconAlert } from './icons'

export interface TabItem {
  key: string
  label: string
  /** Small text after the label, such as a count. */
  count?: string | number
  /** When set, a red exclamation mark follows the label; this text is its accessible name. */
  alert?: string
}

export interface TabsProps {
  tabs: TabItem[]
  /** The key of the selected tab. */
  value: string
  onChange: (key: string) => void
  /** The accessible name of the tab list. */
  label: string
  /** The lighter look of a second strip under a first one: no line, the selected tab in the accent. */
  quiet?: boolean
}

/**
 * A strip of tabs (role="tablist"). A click, or the left and right arrow keys, choose a tab and call
 * `onChange` with its key; the arrows wrap round at the ends and move the focus with the selection.
 * Only the selected tab is a tab stop, as in the ARIA tabs pattern.
 * `label` names the list for screen readers; `quiet` gives it the look of a second strip.
 */
export function Tabs({ tabs, value, onChange, label, quiet = false }: TabsProps) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([])

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!step || tabs.length === 0) return
    event.preventDefault()
    const next = (index + step + tabs.length) % tabs.length
    onChange(tabs[next].key)
    buttons.current[next]?.focus()
  }

  // When no tab matches `value`, the first one is the tab stop, so the strip stays reachable by keyboard.
  const stop = Math.max(0, tabs.findIndex((tab) => tab.key === value))

  return (
    <div className={`r-tabs${quiet ? ' r-tabs--quiet' : ''}`}>
      <div className="r-tabs__list" role="tablist" aria-label={label}>
        {tabs.map((tab, index) => {
          const selected = tab.key === value
          return (
            <button
              key={tab.key}
              ref={(element) => {
                buttons.current[index] = element
              }}
              type="button"
              role="tab"
              className="r-tabs__tab"
              aria-selected={selected}
              tabIndex={index === stop ? 0 : -1}
              onClick={() => onChange(tab.key)}
              onKeyDown={(event) => onKeyDown(event, index)}
            >
              {tab.label}
              {/* The space keeps the label and the count apart for a screen reader; the flex gap spaces them on screen. */}
              {tab.count !== undefined && (
                <>
                  {' '}
                  <span className="r-tabs__count">{tab.count}</span>
                </>
              )}
              {tab.alert && (
                <span className="r-tabs__alert">
                  <IconAlert size={14} label={tab.alert} />
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
