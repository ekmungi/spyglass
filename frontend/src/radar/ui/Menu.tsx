// Menu: a trigger plus a keyboard-navigable popover list, for actions kept out of sight. The list
// opens out of the trigger's corner and stays mounted while it fades away (usePresence).
import { cloneElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactElement } from 'react'
import { IconSelected } from './icons'
import { usePresence } from './usePresence'

export interface MenuItem {
  id: string
  label: string
  onSelect: () => void
  disabled?: boolean
  checked?: boolean
  hint?: string
}

interface TriggerProps {
  onClick?: (event: React.MouseEvent) => void
  'aria-haspopup'?: string
  'aria-expanded'?: boolean
  'aria-controls'?: string
}

export interface MenuProps {
  label: string
  trigger: ReactElement<TriggerProps>
  items: MenuItem[]
  align?: 'start' | 'end'
}

/** Clone the trigger to open a list of actions; arrows move, Enter selects, Esc or outside click closes. */
export function Menu({ label, trigger, items, align = 'end' }: MenuProps) {
  const [open, setOpen] = useState(false)
  const presence = usePresence(open, '--dur-fast')
  const rootRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const menuId = useId()

  const close = useCallback(() => setOpen(false), [])

  // Measure the list once it is open and slide it back inside the window if an edge is cut off.
  // The nudge is written straight to the element: it is a measurement of the page, not app state.
  useLayoutEffect(() => {
    const list = listRef.current
    if (!open || !list) return
    list.style.transform = ''
    const rect = list.getBoundingClientRect()
    // The list may be mid-entrance, scaled from its anchored corner: take the unscaled width and
    // the anchored edge, which the scaling does not move.
    const width = list.offsetWidth || rect.width
    const left = align === 'end' ? rect.right - width : rect.left
    const right = left + width
    const margin = 8
    let dx = 0
    if (right > window.innerWidth - margin) dx = window.innerWidth - margin - right
    if (left + dx < margin) dx = margin - left
    list.style.transform = dx ? `translateX(${dx}px)` : ''
  }, [open, align])

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) close()
    }
    document.addEventListener('mousedown', onDown)
    // Focus the first enabled item so the keyboard can take over at once.
    listRef.current?.querySelector<HTMLButtonElement>('button:not([aria-disabled="true"])')?.focus()
    return () => document.removeEventListener('mousedown', onDown)
  }, [open, close])

  const onKeyDown = (event: React.KeyboardEvent) => {
    const buttons = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>('button') ?? [])
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'Escape') {
      event.stopPropagation()
      close()
      rootRef.current?.querySelector<HTMLElement>('[aria-haspopup]')?.focus()
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      buttons[(index + 1) % buttons.length]?.focus()
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      buttons[(index - 1 + buttons.length) % buttons.length]?.focus()
    }
  }

  const triggerEl = cloneElement(trigger, {
    onClick: (event: React.MouseEvent) => {
      trigger.props.onClick?.(event)
      setOpen((value) => !value)
    },
    'aria-haspopup': 'menu',
    'aria-expanded': open,
    'aria-controls': open ? menuId : undefined,
  })

  return (
    <div className="r-menu" ref={rootRef} onKeyDown={onKeyDown}>
      {triggerEl}
      {presence.mounted && (
        <ul
          className={`r-menu__list r-menu__list--${align}`}
          role="menu"
          aria-label={label}
          id={menuId}
          ref={listRef}
          data-state={presence.state}
          inert={!open}
        >
          {items.map((item) => (
            <li key={item.id} role="none">
              <button
                type="button"
                role="menuitem"
                className="r-menu__item"
                aria-disabled={item.disabled ? 'true' : undefined}
                onClick={() => {
                  if (item.disabled) return
                  close()
                  item.onSelect()
                }}
              >
                <span>{item.label}</span>
                {item.checked && <IconSelected size={14} className="r-menu__check" label="selected" />}
                {item.hint && !item.checked && <span className="r-menu__hint">{item.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
