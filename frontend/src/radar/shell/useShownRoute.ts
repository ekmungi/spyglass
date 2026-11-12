// useShownRoute: the route the shell shows. A change to a different screen (another page, another
// day's brief, another item) is shown through a View Transition: the browser keeps a picture of
// the old screen, the new one is rendered at once, and shell.css cross-fades the two. Changes
// within one screen (Feed filters, a Settings section) and every change where the API is missing
// or reduced motion is asked for are shown immediately, with no transition.
import { useLayoutEffect, useState } from 'react'
import { flushSync } from 'react-dom'
import { useRoute, type Route } from '../router'
import { prefersReducedMotion } from '../ui/motion'

/** What counts as one screen: the query of a page (filters, a section to scroll to) does not. */
export function screenKey(route: Route): string {
  switch (route.name) {
    case 'today':
      return route.day ? `today/${route.day}` : 'today'
    case 'item':
      return `item/${route.id}`
    default:
      return route.name
  }
}

/**
 * Whether a page change may run as a view transition here and now. A hidden page has no frames, and
 * the transition's update would wait for one; such a change is shown at once instead.
 */
function canTransition(): boolean {
  return (
    typeof document !== 'undefined' &&
    typeof document.startViewTransition === 'function' &&
    document.visibilityState === 'visible' &&
    !prefersReducedMotion()
  )
}

// The newest transition; an older one finishing must not clear the mark the newer one set.
let latestTransition = 0

/**
 * The route to render. It equals the address except for the moment between a page change and the
 * browser's capture of the old screen (one frame), so navigation is never held back longer.
 */
export function useShownRoute(): Route {
  const live = useRoute()
  const [shown, setShown] = useState(live)
  const animate = live !== shown && screenKey(live) !== screenKey(shown) && canTransition()

  // Same screen, or no transition possible: follow the address in this very render.
  if (live !== shown && !animate) setShown(live)

  useLayoutEffect(() => {
    if (!animate) return
    const root = document.documentElement
    const token = ++latestTransition
    const finish = () => {
      if (token === latestTransition) delete root.dataset.pageTransition
    }
    // Set before the browser captures the old screen, so the named parts are captured.
    root.dataset.pageTransition = 'true'
    try {
      const transition = document.startViewTransition(() => {
        // Render the new screen synchronously inside the update, so the browser captures it whole
        // (scroll position already restored by the shell's layout effect).
        flushSync(() => setShown(live))
      })
      // A transition skipped by a newer one rejects `ready`; that is expected, not an error.
      transition.ready?.catch(() => undefined)
      transition.finished.then(finish, finish)
    } catch {
      // The browser refused (for example a hidden document): show the new page without one.
      finish()
      queueMicrotask(() => setShown(live))
    }
  }, [animate, live])

  return shown
}
