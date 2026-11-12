// Settings section "Bring in a page from your browser": first the Send to Spyglass browser
// extension (recommended), then, under "Without installing anything", the bookmark button, built
// for the address this copy of Spyglass runs at and carrying this copy's secret. The secret is read
// from the service (this site only) and serves both; "Make a new button" replaces it.
import { useEffect, useRef, useState } from 'react'
import { getImportButtonKey, rotateImportButtonKey } from '../../api/client'
import { errorMessage } from '../../api/errors'
import { buildBookmarklet, isUsableKey, isUsableOrigin } from '../../import/bookmarklet'
import { Button, SectionHeading } from '../../ui'
import { ExtensionSection } from './ExtensionSection'

/** The id the reader's "How to set this up" link scrolls to. */
export const BRING_IN_SECTION = 'bring-in'

/** The section; scrolls itself into view when `focus` is true (arriving from the reader's hint). */
export function BringInSection({ focus = false, origin = window.location.origin }: { focus?: boolean; origin?: string }) {
  const sectionRef = useRef<HTMLDivElement>(null)
  const linkRef = useRef<HTMLAnchorElement>(null)
  const [clicked, setClicked] = useState(false)
  const [key, setKey] = useState<string | null>(null)
  const [keyError, setKeyError] = useState<string | null>(null)
  const [renewed, setRenewed] = useState(false)
  const [renewError, setRenewError] = useState<string | null>(null)
  const [renewing, setRenewing] = useState(false)
  const usable = isUsableOrigin(origin)

  useEffect(() => {
    if (!usable) return
    const controller = new AbortController()
    getImportButtonKey(controller.signal)
      .then((reply) => (isUsableKey(reply.key) ? setKey(reply.key) : setKeyError('Spyglass gave an unexpected answer. Reload this page and try again.')))
      .catch((cause) => {
        if (!controller.signal.aborted) setKeyError(errorMessage(cause))
      })
    return () => controller.abort()
  }, [usable])

  // React refuses javascript: addresses in href, so the link gets its address directly. The button
  // runs on other sites, never here: Spyglass's own security policy blocks it on this page.
  useEffect(() => {
    if (usable && key) linkRef.current?.setAttribute('href', buildBookmarklet(origin, key))
  }, [origin, usable, key])

  useEffect(() => {
    if (focus) sectionRef.current?.scrollIntoView({ block: 'start' })
  }, [focus])

  const renew = async () => {
    setRenewing(true)
    try {
      const reply = await rotateImportButtonKey()
      setKey(reply.key)
      setRenewError(null)
      setRenewed(true)
      setClicked(false)
    } catch (cause) {
      setRenewError(errorMessage(cause))
    } finally {
      setRenewing(false)
    }
  }

  return (
    <div ref={sectionRef} id={BRING_IN_SECTION}>
      <ExtensionSection
        keyValue={key}
        keyError={usable ? keyError : 'Open Spyglass at its usual http://localhost address.'}
        renewed={renewed}
      />
      <section aria-labelledby="settings-bring-in" className="rst-section">
        <SectionHeading id="settings-bring-in">Without installing anything</SectionHeading>
        <p className="r-meta">
          Drag the button below to your browser&rsquo;s bookmarks bar. When an article is behind a paywall or a bot check, open it in your browser as usual
          and click Send to Spyglass in the bookmarks bar. A small Spyglass window shows the page&rsquo;s address and first lines, and nothing is added
          until you press Add to Spyglass.
        </p>
        {!usable ? (
          <p className="r-error-text">The button cannot be made for this address ({origin}). Open Spyglass at its usual http://localhost address.</p>
        ) : key ? (
          <p className="rst-actions">
            <a
              ref={linkRef}
              className="r-btn r-btn--secondary"
              draggable
              onClick={(event) => {
                event.preventDefault()
                setClicked(true)
              }}
            >
              Send to Spyglass
            </a>
            <Button variant="quiet" onClick={renew} disabled={renewing}>
              {renewing ? 'Making a new button…' : 'Make a new button'}
            </Button>
          </p>
        ) : keyError ? (
          <p className="r-error-text" role="alert">The button could not be made: {keyError}</p>
        ) : (
          <p className="r-meta" role="status">Preparing the button…</p>
        )}
        {clicked && <p className="r-meta" role="status">Drag the button to your bookmarks bar; it works on other sites, not here.</p>}
        {renewError && <p className="r-error-text" role="alert">A new button could not be made: {renewError}</p>}
        {renewed && (
          <p className="r-meta" role="status">
            This is a new button: drag it to your bookmarks bar in place of the old one, which no longer works.
          </p>
        )}
        <p className="r-meta">
          Make a new button if you think someone else has your button. Some sites block the button. Then save the page from your browser (Ctrl+S) and use
          Add link, then Add a file, or copy the text and use Paste the text.
        </p>
      </section>
    </div>
  )
}
