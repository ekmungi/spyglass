// FirstStartGate: asks the service whether this is a first start (or a browser guide is waiting) and,
// if so, shows the welcome page in place of the app until it finishes.
import { useEffect, useState, type ReactNode } from 'react'
import { getFirstStart } from '../../api/client'
import type { FirstStart } from '../../api/types'
import { WelcomePage } from './WelcomePage'

/**
 * Renders the app while the answer is pending and when it fails (so a service without this route
 * behaves as before), and the welcome page when a first start or a browser guide is waiting.
 */
export function FirstStartGate({ children }: { children: ReactNode }) {
  const [firstStart, setFirstStart] = useState<FirstStart | null>(null)
  const [finished, setFinished] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getFirstStart(controller.signal).then(setFirstStart, () => setFirstStart(null))
    return () => controller.abort()
  }, [])

  const waiting = firstStart !== null && (firstStart.needed || firstStart.browsers.length > 0)
  if (waiting && !finished) return <WelcomePage firstStart={firstStart} onDone={() => setFinished(true)} />
  return <>{children}</>
}
