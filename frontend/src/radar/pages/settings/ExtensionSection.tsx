// Settings section "Browser extension (recommended)": what the Send to Spyglass extension does,
// how to install it, and the key to paste into it. The key is the same one the bookmark button
// uses; it is read by the parent (this site only) and shown masked until the reader asks for it.
import { useState } from 'react'
import { Button, SectionHeading, toast } from '../../ui'

/** The key as dots, so it is not readable over the reader's shoulder. */
const MASK = '•'.repeat(32)

/** Copy the key to the clipboard and confirm (or explain the failure) with a toast. */
function copyKey(key: string): void {
  if (!navigator.clipboard) {
    toast('Could not copy to the clipboard. Show the key and copy it by hand.', { tone: 'error' })
    return
  }
  navigator.clipboard.writeText(key).then(
    () => toast('Key copied'),
    () => toast('Could not copy to the clipboard. Show the key and copy it by hand.', { tone: 'error' }),
  )
}

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
  return (
    <section aria-labelledby="settings-extension" className="rst-section">
      <SectionHeading id="settings-extension">Browser extension (recommended)</SectionHeading>
      <p className="r-meta">
        Install the Send to Spyglass extension once. Then, on any page you are reading, including pages behind a paywall or a bot check, click its
        button and the page is added to Spyglass. It only acts when you click, and it talks only to Spyglass on this computer.
      </p>
      <ol className="rst-steps r-meta">
        <li>
          Open your browser&rsquo;s extensions page (type <code>chrome://extensions</code> in the address bar; in Vivaldi, <code>vivaldi://extensions</code>) and
          switch on Developer mode.
        </li>
        <li>
          Press Load unpacked and choose the folder named <code>browser-extension</code>, which is inside the Spyglass folder.
        </li>
        <li>Pin its button to the toolbar, open its settings, paste the key below and press Test connection.</li>
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
        <p className="r-meta" role="status">The key changed. Paste the new key into the extension&rsquo;s settings to connect it again.</p>
      )}
      <p className="r-meta">
        &ldquo;Make a new button&rdquo; (below) also replaces this key, which disconnects the extension until you paste the new one into it.
      </p>
    </section>
  )
}
