// "Add a file": a .pdf, or a page saved from the browser as .html or .mhtml, becomes the readable
// copy of an address (POST /import/file). A PDF is also kept for the built-in viewer.
import { useState, type FormEvent } from 'react'
import { importFile } from '../api/client'
import { errorMessage } from '../api/errors'
import { safeHttpUrl } from '../lib/safeUrl'
import { Button, Dialog } from '../ui'
import { FILE_ACCEPT, fileProblem, MAX_FILE_MB } from './messages'
import type { ImportDialogProps } from './PasteTextDialog'
import './import.css'

/** The file dialog: the page's address and one file. */
export function FileDialog({ open, onClose, onBack, onAdded }: ImportDialogProps) {
  const [url, setUrl] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!safeHttpUrl(url.trim())) return setError('Enter the full web address of the page, starting with http:// or https://.')
    const problem = fileProblem(file)
    if (problem || !file) return setError(problem)
    setBusy(true)
    setError(null)
    try {
      onAdded(await importFile(url.trim(), file), url.trim())
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
      title="Add a file"
      footer={
        <>
          <Button variant="quiet" onClick={onBack}>
            Back
          </Button>
          <Button variant="primary" type="submit" form="r-add-file" disabled={busy}>
            {busy ? 'Adding…' : 'Add the file'}
          </Button>
        </>
      }
    >
      <form id="r-add-file" onSubmit={submit} noValidate>
        <label className="r-field">
          Web address of the page
          <input className="r-input" type="url" inputMode="url" placeholder="https://" value={url} onChange={(event) => setUrl(event.target.value)} autoComplete="off" />
        </label>
        <label className="r-field">
          File
          <input className="rim-file" type="file" accept={FILE_ACCEPT} onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        </label>
        {error && (
          <p className="r-error-text" role="alert">
            {error}
          </p>
        )}
        <p className="r-meta">A PDF, or a page saved from your browser with Ctrl+S (.html, or .mhtml for a single file). Up to {MAX_FILE_MB} MB.</p>
      </form>
    </Dialog>
  )
}
