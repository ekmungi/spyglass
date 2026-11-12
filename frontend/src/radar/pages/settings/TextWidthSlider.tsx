// The Text width slider. While it is being dragged only its own label follows the hand; the page
// width changes once, a moment after release, so the layout never moves under the pointer. For the
// keyboard the same delay works as a debounce: the width applies after the last arrow-key press.
import { useCallback, useEffect, useRef, useState } from 'react'
import { TEXT_WIDTH, textWidthLabel } from '../../appearance/catalog'

/** How long after release (or the last key press) the new width is applied and stored. */
export const APPLY_DELAY_MS = 250

export interface TextWidthSliderProps {
  /** The applied width. */
  value: number
  /** Apply and remember a width. */
  onCommit: (px: number) => void
}

/** The slider with its "Wide · 900px" label. Remount it (a new `key`) to drop a pending change. */
export function TextWidthSlider({ value, onCommit }: TextWidthSliderProps) {
  const [draft, setDraft] = useState<number | null>(null)
  const timer = useRef<number | null>(null)
  const dragging = useRef(false)
  const pending = useRef<number | null>(null)
  const commit = useRef(onCommit)
  useEffect(() => {
    commit.current = onCommit
  })
  const shown = draft ?? value

  const cancel = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
  }, [])

  /** Apply `px` after the delay, replacing any change still waiting. */
  const schedule = useCallback(
    (px: number) => {
      cancel()
      timer.current = window.setTimeout(() => {
        timer.current = null
        pending.current = null
        commit.current(px)
        setDraft(null)
      }, APPLY_DELAY_MS)
    },
    [cancel],
  )

  // A drag ends wherever the pointer is released, so the end is heard on the whole window.
  useEffect(() => {
    const end = () => {
      if (!dragging.current) return
      dragging.current = false
      if (pending.current !== null) schedule(pending.current)
    }
    const events = ['pointerup', 'pointercancel', 'touchend', 'mouseup'] as const
    events.forEach((name) => window.addEventListener(name, end))
    return () => {
      events.forEach((name) => window.removeEventListener(name, end))
      // Leaving during the delay drops the change rather than applying a stale value later.
      cancel()
    }
  }, [schedule, cancel])

  const startDrag = () => {
    dragging.current = true
    cancel()
  }

  return (
    <>
      <div className="rst-width">
        <span className="r-meta" aria-hidden="true">
          Narrow
        </span>
        <input
          type="range"
          className="rst-width__slider"
          aria-label="Text width"
          aria-valuetext={textWidthLabel(shown)}
          min={TEXT_WIDTH.min}
          max={TEXT_WIDTH.max}
          step={TEXT_WIDTH.step}
          value={shown}
          onPointerDown={startDrag}
          onTouchStart={startDrag}
          onMouseDown={startDrag}
          onChange={(event) => {
            const px = Number(event.target.value)
            setDraft(px)
            pending.current = px
            if (!dragging.current) schedule(px)
          }}
        />
        <span className="r-meta" aria-hidden="true">
          Wide
        </span>
      </div>
      <p className="rst-width__value" data-testid="text-width-value">
        {textWidthLabel(shown)}
      </p>
    </>
  )
}
