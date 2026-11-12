// AddLinkDialog: send a link into Spyglass from anywhere (POST /capture); it lands in "From you".
// Two quieter doors serve pages Spyglass cannot read itself (a paywall, a bot check): paste the
// text, or add a saved file. Once something is added, the dialog offers "Follow more like this",
// which opens the shared follow dialog for the same address.
import { useState, type FormEvent } from 'react'
import { captureLink } from '../api/client'
import { errorMessage } from '../api/errors'
import type { RadarItem } from '../api/types'
import { FollowDialog } from '../follow/FollowDialog'
import { FileDialog } from '../import/FileDialog'
import { PasteTextDialog } from '../import/PasteTextDialog'
import { safeHttpUrl } from '../lib/safeUrl'
import { navigate } from '../router'
import { Button, Dialog } from '../ui'

/** The Add link dialog: a URL, an optional note, and one button; then what to do with the added link. */
export function AddLinkDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [url, setUrl] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [added, setAdded] = useState<{ item: RadarItem; url: string; page?: boolean } | null>(null)
  const [following, setFollowing] = useState(false)
  // Which door is open: the plain link form, pasted text or a saved file.
  const [door, setDoor] = useState<'link' | 'text' | 'file'>('link')

  const close = () => {
    setError(null)
    setAdded(null)
    setFollowing(false)
    setDoor('link')
    onClose()
  }
  const pageAdded = (item: RadarItem, address: string) => setAdded({ item, url: address, page: true })

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!safeHttpUrl(url)) {
      setError('Enter a full web address starting with http:// or https://.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const address = url.trim()
      const item = await captureLink({ url: address, note: note.trim() || undefined })
      setUrl('')
      setNote('')
      setAdded({ item, url: address })
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  if (added) {
    return (
      <>
        <Dialog
          open={open && !following}
          onClose={close}
          title={added.page ? 'Page added' : 'Link added'}
          footer={
            <>
              <Button variant="quiet" onClick={close}>
                Done
              </Button>
              <Button
                variant="quiet"
                onClick={() => {
                  navigate({ name: 'item', id: added.item.id })
                  close()
                }}
              >
                Open
              </Button>
              <Button variant="secondary" onClick={() => setFollowing(true)}>
                Follow more like this
              </Button>
            </>
          }
        >
          <p className="r-meta">It is in today&rsquo;s From you section. Spyglass can also suggest topics from it to keep following.</p>
        </Dialog>
        <FollowDialog open={open && following} source={{ kind: 'url', url: added.url }} onClose={close} />
      </>
    )
  }

  if (door === 'text') return <PasteTextDialog open={open} onClose={close} onBack={() => setDoor('link')} onAdded={pageAdded} />
  if (door === 'file') return <FileDialog open={open} onClose={close} onBack={() => setDoor('link')} onAdded={pageAdded} />

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Add a link"
      footer={
        <>
          <Button variant="quiet" onClick={close}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="r-add-link" disabled={busy}>
            {busy ? 'Adding…' : 'Add link'}
          </Button>
        </>
      }
    >
      <form id="r-add-link" onSubmit={submit} noValidate>
        <label className="r-field">
          Web address
          <input className="r-input" type="url" inputMode="url" placeholder="https://" value={url} onChange={(event) => setUrl(event.target.value)} autoComplete="off" />
        </label>
        <label className="r-field">
          Note for yourself (optional)
          <textarea className="r-textarea" rows={2} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Why you saved it" />
        </label>
        {error && (
          <p className="r-error-text" role="alert">
            {error}
          </p>
        )}
        <p className="r-meta">Spyglass reads it and adds it to today&rsquo;s From you section.</p>
        <p className="rim-doors">
          Behind a paywall or a bot check?{' '}
          <button type="button" onClick={() => setDoor('text')}>
            Paste the text
          </button>{' '}
          or{' '}
          <button type="button" onClick={() => setDoor('file')}>
            add a saved file
          </button>
          .
        </p>
      </form>
    </Dialog>
  )
}
