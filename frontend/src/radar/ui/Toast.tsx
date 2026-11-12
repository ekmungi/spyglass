// ToastViewport: renders the toast queue at the bottom centre, announced politely to screen readers.
// A dismissed toast stays a moment to fade out; the others then glide into its place.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { motionMs, motionToken } from './motion'
import { dismissToast, reconcileToasts, subscribeToasts, type ShownToast } from './toastStore'

/**
 * Slide each toast from where it was to where it is now (FLIP), using `translate`. Positions are
 * read in viewport terms because the stack is anchored to the bottom: a new toast moves the older
 * ones up by growing the container, not by changing their place inside it.
 */
function glideToNewPlaces(list: HTMLElement, previousTops: Map<number, number>): Map<number, number> {
  const tops = new Map<number, number>()
  const duration = motionMs('--dur')
  for (const element of Array.from(list.children) as HTMLElement[]) {
    const id = Number(element.dataset.toastId)
    const top = Math.round(element.getBoundingClientRect().top)
    tops.set(id, top)
    const before = previousTops.get(id)
    if (duration > 0 && before !== undefined && before !== top && typeof element.animate === 'function') {
      element.animate([{ translate: `0 ${before - top}px` }, { translate: '0 0' }], { duration, easing: motionToken('--ease-enter') })
    }
  }
  return tops
}

/** Mount once in the app shell; shows messages queued with `toast()`. */
export function ToastViewport() {
  const [shown, setShown] = useState<readonly ShownToast[]>([])
  const liveIds = useRef<ReadonlySet<number>>(new Set())
  const listRef = useRef<HTMLDivElement>(null)
  const tops = useRef(new Map<number, number>())

  useEffect(
    () =>
      subscribeToasts((queue) => {
        const exitMs = motionMs('--dur-fast')
        const next = new Set(queue.map((item) => item.id))
        const gone = [...liveIds.current].filter((id) => !next.has(id))
        liveIds.current = next
        setShown((previous) => reconcileToasts(previous, queue, exitMs > 0))
        if (gone.length > 0 && exitMs > 0) {
          window.setTimeout(() => setShown((previous) => previous.filter((entry) => !gone.includes(entry.item.id))), exitMs)
        }
      }),
    [],
  )

  useLayoutEffect(() => {
    if (listRef.current) tops.current = glideToNewPlaces(listRef.current, tops.current)
  }, [shown])

  return (
    <div className="r-toasts" role="status" aria-live="polite" ref={listRef}>
      {shown.map(({ item, leaving }) => (
        <div
          key={item.id}
          data-toast-id={item.id}
          data-state={leaving ? 'closed' : 'open'}
          aria-hidden={leaving || undefined}
          className={`r-toast${item.tone === 'error' ? ' r-toast--error' : ''}`}
        >
          <span>{item.message}</span>
          {item.action && (
            <button
              type="button"
              tabIndex={leaving ? -1 : undefined}
              onClick={() => {
                dismissToast(item.id)
                item.action?.onClick()
              }}
            >
              {item.action.label}
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
