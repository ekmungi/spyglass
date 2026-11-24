// The browser part of the first-start page: the "Load unpacked" steps for each browser that setup
// was asked to guide, with a button that opens that browser's extensions page, and Done / Skip.
import { useEffect, useState } from 'react'
import { dismissSetupGuide, getExtensionFolder, openExtensionsPage } from '../../api/client'
import { errorMessage } from '../../api/errors'
import type { DesktopBrowser } from '../../api/types'
import { Button, SectionHeading, toast } from '../../ui'

interface BrowserGuideProps {
  /** The browsers setup asked a guide for; never empty. */
  browsers: DesktopBrowser[]
  /** Called once the guide has been forgotten (or could not be), so the app can show its normal page. */
  onDone: () => void
}

/** The steps to load the extension in each ticked browser, and the buttons that end the guide. */
export function BrowserGuide({ browsers, onDone }: BrowserGuideProps) {
  const [folder, setFolder] = useState<string | null>(null)

  // Without the folder (a failed read) the steps fall back to naming the folder to look for.
  useEffect(() => {
    const controller = new AbortController()
    getExtensionFolder(controller.signal).then((reply) => setFolder(reply.folder), () => setFolder(null))
    return () => controller.abort()
  }, [])

  const openPage = async (browser: DesktopBrowser) => {
    try {
      await openExtensionsPage(browser.id)
    } catch (cause) {
      toast(errorMessage(cause), { tone: 'error' })
    }
  }

  // The guide is forgotten on the service so it does not return at the next start. If that fails,
  // the reader is told and still moves on: a guide shown once more costs less than a stuck page.
  const finish = async () => {
    try {
      await dismissSetupGuide()
    } catch (cause) {
      toast(`The guide could not be hidden for good: ${errorMessage(cause)}`, { tone: 'error' })
    }
    onDone()
  }

  return (
    <section aria-labelledby="welcome-browser" className="rst-section">
      <SectionHeading id="welcome-browser">Add the browser extension</SectionHeading>
      <p className="r-meta">
        The Send to Spyglass extension adds the page you are reading to Spyglass with one click. Do these steps once in each browser you chose
        during setup. The extension only acts when you click it, and it talks only to Spyglass on this computer.
      </p>
      <ol className="rst-steps r-meta">
        <li>
          Open your browser&rsquo;s extensions page.
          <span className="rst-actions">
            {browsers.map((browser) => (
              <Button key={browser.id} size="sm" variant="secondary" onClick={() => void openPage(browser)}>
                {`Open ${browser.name}’s extensions page`}
              </Button>
            ))}
          </span>
        </li>
        <li>Switch on Developer mode.</li>
        <li>
          {folder ? (
            <>
              Press Load unpacked and choose this folder: <code className="rst-key__value">{folder}</code>
            </>
          ) : (
            <>Press Load unpacked and choose the folder named <code>browser-extension</code>, which is inside the Spyglass folder.</>
          )}
        </li>
        <li>
          Pin its button to the toolbar, open its settings and press Test connection. If the key box is empty, copy the key from Settings, under
          Browser extension, and paste it there.
        </li>
      </ol>
      <div className="rst-actions">
        <Button variant="primary" onClick={() => void finish()}>
          Done
        </Button>
        <Button variant="quiet" onClick={() => void finish()}>
          Skip for now
        </Button>
      </div>
    </section>
  )
}
