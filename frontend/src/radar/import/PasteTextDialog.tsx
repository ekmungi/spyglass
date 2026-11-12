// "Paste the text": the reader copies an article they can read in their browser and pastes it here
// with its address; it becomes the item's readable copy (POST /import/text).
import { useState, type FormEvent } from 'react'
import { importText } from '../api/client'
import { errorMessage } from '../api/errors'
import type { RadarItem } from '../api/types'
import { safeHttpUrl } from '../lib/safeUrl'
import { Button, Dialog } from '../ui'
import { MAX_HTML_CHARS } from './messages'
import './import.css'

export interface ImportDialogProps {
  open: boolean
  onClose: () => void
  /** Back to the plain "Add a link" form. */
  onBack: () => void
  onAdded: (item: RadarItem, url: string) => void
}

/** The paste dialog: the page's address and a large text area. */
export function PasteTextDialog({ open, onClose, onBack, onAdded }: ImportDialogProps) {
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const address = safeHttpUrl(url.trim())
    if (!address) return setError('Enter the full web address of the article, starting with http:// or https://.')
    if (!text.trim()) return setError('Paste the text of the article first.')
    if (text.length > MAX_HTML_CHARS) return setError('The text is longer than 6 MB. Save the page and use Add a file instead.')
    setBusy(true)
    setError(null)
    try {
      onAdded(await importText({ url: url.trim(), text }), url.trim())
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Paste the text"
      footer={
        <>
          <Button variant="quiet" onClick={onBack}>
            Back
          </Button>
          <Button variant="primary" type="submit" form="r-paste-text" disabled={busy}>
            {busy ? 'Adding…' : 'Add the text'}
          </Button>
        </>
      }
    >
      <form id="r-paste-text" onSubmit={submit} noValidate>
        <label className="r-field">
          Web address of the article
          <input className="r-input" type="url" inputMode="url" placeholder="https://" value={url} onChange={(event) => setUrl(event.target.value)} autoComplete="off" />
        </label>
        <label className="r-field">
          The article&rsquo;s text
          <textarea className="r-textarea" rows={10} value={text} onChange={(event) => setText(event.target.value)} placeholder="Select the article in your browser, copy it and paste it here." />
        </label>
        {error && (
          <p className="r-error-text" role="alert">
            {error}
          </p>
        )}
        <p className="r-meta">For a page Spyglass cannot read itself, such as one behind a paywall. The text becomes its readable copy and is judged again.</p>
      </form>
    </Dialog>
  )
}
