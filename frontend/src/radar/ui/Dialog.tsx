// Dialog: a small modal with a title, body and footer; Esc and the backdrop close it. It stays
// mounted while its exit plays (usePresence) and hands over smoothly to a dialog that replaces it.
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { IconButton } from './IconButton'
import { IconClose } from './icons'
import { usePresence } from './usePresence'

export interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  /**
   * For a dialog with steps: change it when the step changes, and the body fades in afresh (the
   * old step leaves at once, the new one fades in over --dur).
   */
  contentKey?: string
}

// A dialog that appears within this many ms of another one vanishing while still open is a
// hand-over (one dialog replaced by the next in the same click), so the backdrop must not fade out
// and in again. A dialog that closed normally and played its exit does not count.
const HANDOVER_MS = 80
let lastVanished: { owner: symbol; at: number } | null = null

/** A modal dialog; focuses its first field on open and returns focus to the opener on close. */
export function Dialog({ open, onClose, title, children, footer, contentKey }: DialogProps) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const backdropRef = useRef<HTMLDivElement>(null)
  const [owner] = useState(() => Symbol('dialog'))
  const presence = usePresence(open, '--dur')
  const openRef = useRef(open)

  useLayoutEffect(() => {
    openRef.current = open
  }, [open])

  useEffect(() => {
    if (!open) return
    const opener = document.activeElement as HTMLElement | null
    const first = panelRef.current?.querySelector<HTMLElement>('input, textarea, select, button:not([aria-label="Close"])')
    first?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      opener?.focus?.()
    }
  }, [open, onClose])

  // A new step takes the keyboard focus too: its first field (or button), as on opening. The old
  // step's control that was clicked has just been removed, which would otherwise drop focus.
  const stepRef = useRef(contentKey)
  useEffect(() => {
    if (stepRef.current === contentKey) return
    stepRef.current = contentKey
    panelRef.current?.querySelector<HTMLElement>('.r-dialog__step :is(input, textarea, select, button)')?.focus()
  }, [contentKey])

  // Mark a hand-over before the first frame is styled, and record when this dialog vanishes while
  // open. The owner check keeps React's development double-mount from mistaking a dialog for its
  // own successor.
  useLayoutEffect(() => {
    const backdrop = backdropRef.current
    if (!presence.mounted || !backdrop) return
    if (lastVanished && lastVanished.owner !== owner && performance.now() - lastVanished.at < HANDOVER_MS) backdrop.dataset.swap = 'true'
    return () => {
      // The latest committed `open` is wanted here, which is why it is read from the ref.
      if (openRef.current) lastVanished = { owner, at: performance.now() }
    }
  }, [presence.mounted, owner])

  if (!presence.mounted) return null
  return (
    <div
      ref={backdropRef}
      className="r-dialog-backdrop"
      data-state={presence.state}
      inert={!open}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="r-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={panelRef}>
        <div className="r-dialog__head">
          <h2 className="r-dialog__title" id={titleId}>
            {title}
          </h2>
          <IconButton label="Close" icon={<IconClose size={16} />} onClick={onClose} tooltipSide="bottom" />
        </div>
        {contentKey === undefined ? (
          children
        ) : (
          <div key={contentKey} className="r-dialog__step r-appear">
            {children}
          </div>
        )}
        {footer && <div className="r-dialog__footer">{footer}</div>}
      </div>
    </div>
  )
}
