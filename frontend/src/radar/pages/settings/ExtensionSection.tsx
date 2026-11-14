// Settings section "Browser extension (recommended)": what the Send to Spyglass extension does,
// how to install it, and the key to paste into it. The key is the same one the bookmark button
// uses; it is read by the parent (this site only) and shown masked until the reader asks for it.
import { useEffect, useState } from 'react'
import { getBrowsers, getExtensionFolder, openExtensionsPage } from '../../api/client'
import { errorMessage } from '../../api/errors'
import type { DesktopBrowser } from '../../api/types'
import { Button, SectionHeading, toast } from '../../ui'

/** The key as dots, so it is not readable over the reader's shoulder. */
const MASK = '•'.repeat(32)

/** Copy text to the clipboard and confirm (or explain the failure) with a toast. */
function copyText(text: string, done: string, failed: string): void {
  if (!navigator.clipboard) {
    toast(failed, { tone: 'error' })
    return
  }
  navigator.clipboard.writeText(text).then(
    () => toast(done),
    () => toast(failed, { tone: 'error' }),
  )
}

/** Copy the key to the clipboard and confirm (or explain the failure) with a toast. */
const copyKey = (key: string) => copyText(key, 'Key copied', 'Could not copy to the clipboard. Show the key and copy it by hand.')

/** Copy the extension folder's path, which the browser's file picker needs. */
const copyFolder = (folder: string) =>
  copyText(folder, 'Folder copied', 'Could not copy to the clipboard. Select the folder path and copy it by hand.')

interface ExtensionSectionProps {
  /** The key, or null while it is being read or when it could not be. */
  keyValue: string | null
  /** Why the key could not be read, when it could not. */
  keyError: string | null
  /** True after "Make a new button" replaced the key during this visit. */
  renewed: boolean
}

/** The extension section: three sentences, three steps, and the key with Show and Copy. */
export function ExtensionSection({ keyValue, keyError, renewed }: ExtensionSectionProps) {
  const [shown, setShown] = useState(false)
  const [browsers, setBrowsers] = useState<DesktopBrowser[]>([])
  const [folder, setFolder] = useState<string | null>(null)
  const [openError, setOpenError] = useState<string | null>(null)

  // Both come from the desktop app. A developer run answers neither, and the steps then fall back to
  // typing the address by hand and finding the folder named browser-extension.
  useEffect(() => {
    const controller = new AbortController()
    getBrowsers(controller.signal).then(setBrowsers, () => setBrowsers([]))
    getExtensionFolder(controller.signal).then((reply) => setFolder(reply.folder), () => setFolder(null))
    return () => controller.abort()
  }, [])

  const openPage = async (browser: DesktopBrowser) => {
    try {
      await openExtensionsPage(browser.id)
      setOpenError(null)
    } catch (cause) {
      setOpenError(errorMessage(cause))
    }
  }

  return (
    <section aria-labelledby="settings-extension" className="rst-section">
      <SectionHeading id="settings-extension">Browser extension (recommended)</SectionHeading>
      <p className="r-meta">
        Install the Send to Spyglass extension once. Then, on any page you are reading, including pages behind a paywall or a bot check, click its
        button and the page is added to Spyglass. It only acts when you click, and it talks only to Spyglass on this computer.
      </p>
      <ol className="rst-steps r-meta">
        <li>
          Open your browser&rsquo;s extensions page
          {browsers.length > 0 ? (
            '.'
          ) : (
            <>
              {' '}
              (type <code>chrome://extensions</code> in the address bar; in Vivaldi, <code>vivaldi://extensions</code>).
            </>
          )}
          {browsers.length > 0 && (
            <span className="rst-actions">
              {browsers.map((browser) => (
                <Button key={browser.id} size="sm" variant="secondary" onClick={() => void openPage(browser)}>
                  Open in {browser.name}
                </Button>
              ))}
            </span>
          )}
          {openError && (
            <span className="r-error-text" role="alert">
              {openError}
            </span>
          )}
        </li>
        <li>Switch on Developer mode.</li>
        <li>
          {folder ? (
            <>
              Press Load unpacked and choose this folder: <code className="rst-key__value">{folder}</code>{' '}
              <Button size="sm" variant="secondary" onClick={() => copyFolder(folder)}>
                Copy folder
              </Button>
            </>
          ) : (
            <>
              Press Load unpacked and choose the folder named <code>browser-extension</code>, which is inside the Spyglass folder.
            </>
          )}
        </li>
        <li>Pin its button to the toolbar, open its settings and press Test connection. If the key box is empty, paste the key below.</li>
      </ol>
      {keyValue ? (
        <p className="rst-key">
          <span className="r-meta">Key</span>
          <code className="rst-key__value" data-shown={shown}>
            {shown ? keyValue : MASK}
          </code>
          <Button size="sm" variant="quiet" aria-pressed={shown} onClick={() => setShown((now) => !now)}>
            {shown ? 'Hide' : 'Show'}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => copyKey(keyValue)}>
            Copy
          </Button>
        </p>
      ) : keyError ? (
        <p className="r-error-text">The key could not be read: {keyError}</p>
      ) : (
        <p className="r-meta" role="status">Reading the key…</p>
      )}
      {renewed && (
        <p className="r-meta" role="status">
          The key changed. Press Reload on the extension&rsquo;s card on your browser&rsquo;s extensions page so it picks up the new key, and
          paste the new key into the extension&rsquo;s settings if it still shows as disconnected.
        </p>
      )}
      <p className="r-meta">
        &ldquo;Make a new button&rdquo; (below) also replaces this key, which disconnects the extension until you press Reload on its card on the browser&rsquo;s extensions page.
      </p>
    </section>
  )
}
