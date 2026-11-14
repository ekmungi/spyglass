// Settings section "Spyglass on this computer": start with Windows, and Quit. The switch is offered
// only by the desktop app. After Quit the service is gone, so the section swaps itself for one
// sentence and stops asking the service anything.
import { useEffect, useState } from 'react'
import { getAutostart, quitSpyglass, setAutostart } from '../../api/client'
import { errorMessage } from '../../api/errors'
import { Button, SectionHeading, toast } from '../../ui'
import { Switch } from '../sources/Switch'

/** What the reader sees once the service has been stopped. */
export const STOPPED_MESSAGE = 'Spyglass has stopped. Open it again from the Start menu.'

/** The section: the "Start with Windows" switch (when offered) and the "Quit Spyglass" button. */
export function DesktopSection() {
  const [autostart, setAutostartState] = useState<{ available: boolean; enabled: boolean } | null>(null)
  const [changing, setChanging] = useState(false)
  const [quitting, setQuitting] = useState(false)
  const [stopped, setStopped] = useState(false)

  // A failed read hides the switch rather than showing a broken one: without an answer there is
  // nothing true to show, and Quit still works.
  useEffect(() => {
    const controller = new AbortController()
    getAutostart(controller.signal).then(setAutostartState, () => setAutostartState(null))
    return () => controller.abort()
  }, [])

  const toggle = async (next: boolean) => {
    setChanging(true)
    try {
      setAutostartState(await setAutostart(next))
    } catch (cause) {
      // The switch stays as it was, because the setting did not change.
      toast(errorMessage(cause), { tone: 'error' })
    } finally {
      setChanging(false)
    }
  }

  const quit = async () => {
    setQuitting(true)
    try {
      await quitSpyglass()
      setStopped(true)
    } catch (cause) {
      toast(errorMessage(cause), { tone: 'error' })
    } finally {
      setQuitting(false)
    }
  }

  return (
    <section aria-labelledby="settings-desktop" className="rst-section">
      <SectionHeading id="settings-desktop">Spyglass on this computer</SectionHeading>
      {stopped ? (
        <p className="r-meta" role="status">
          {STOPPED_MESSAGE}
        </p>
      ) : (
        <>
          {autostart?.available && (
            <p className="rst-switch-line">
              <Switch label="Start with Windows" checked={autostart.enabled} disabled={changing} onChange={(next) => void toggle(next)} />
              <span className="rst-switch-line__text">Start with Windows</span>
            </p>
          )}
          <p className="rst-actions">
            <Button variant="secondary" onClick={() => void quit()} disabled={quitting}>
              Quit Spyglass
            </Button>
          </p>
        </>
      )}
    </section>
  )
}
