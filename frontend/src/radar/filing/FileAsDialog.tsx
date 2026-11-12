// FileAsDialog: "File as…" for one item. The reader picks the kind of note, optionally a project and
// a one-line note, and the item joins the To file queue. Nothing is opened and nothing is written.
import { useEffect, useRef, useState } from 'react'
import { getFilingQueue } from '../api/client'
import type { FilingKind } from '../api/types'
import { queueItem } from '../state/filingState'
import { Button, Dialog, Select, toast } from '../ui'
import { KIND_CHOICES } from './kinds'
import { useProjectNames } from './useProjectNames'
import './filing.css'

/** The note is cut to this many characters by the service; the field stops there too. */
const NOTE_MAX = 500

export interface FileAsDialogProps {
  itemId: number
  /** True when the item already waits: the dialog then changes its choices instead of adding it. */
  changing?: boolean
  onClose: () => void
}

/** The dialog; mount it only while open, so each opening starts from the item's stored choices. */
export function FileAsDialog({ itemId, changing = false, onClose }: FileAsDialogProps) {
  const [kind, setKind] = useState<FilingKind>('resource')
  const [project, setProject] = useState('')
  const [note, setNote] = useState('')
  const touched = useRef(false)
  const projectNames = useProjectNames()

  // When changing, start from what the service stored for this item (unless the reader already typed).
  useEffect(() => {
    if (!changing) return
    const controller = new AbortController()
    getFilingQueue(controller.signal).then(
      (queue) => {
        const entry = queue.waiting.find((row) => row.item.id === itemId)
        if (!entry || touched.current || controller.signal.aborted) return
        setKind(entry.kind)
        setProject(entry.project ?? '')
        setNote(entry.note)
      },
      () => undefined, // Without the stored choices the dialog simply starts from the defaults.
    )
    return () => controller.abort()
  }, [changing, itemId])

  const confirm = () => {
    onClose()
    void queueItem(itemId, { kind, ...(project ? { project } : {}), ...(note.trim() ? { note: note.trim() } : {}) }, { quiet: changing }).then((ok) => {
      if (ok && changing) toast('Filing choices updated')
    })
  }

  const projectOptions = [
    { value: '', label: 'No project' },
    ...(project && !projectNames.includes(project) ? [{ value: project, label: project }] : []),
    ...projectNames.map((name) => ({ value: name, label: name })),
  ]

  return (
    <Dialog
      open
      onClose={onClose}
      title={changing ? 'Change how this is filed' : 'File as…'}
      footer={
        <>
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={confirm}>
            {changing ? 'Save changes' : 'Add to the queue'}
          </Button>
        </>
      }
    >
      <p className="rfq-lede">The item joins your filing queue. Nothing is written to your vault until you choose File now and say yes in Claude Code.</p>
      <div
        className="rfq-fields"
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            confirm()
          }
        }}
      >
        <Select
          label="File it as"
          value={kind}
          options={KIND_CHOICES}
          onChange={(value) => {
            touched.current = true
            setKind(value as FilingKind)
          }}
        />
        <Select
          label="Project"
          value={project}
          options={projectOptions}
          onChange={(value) => {
            touched.current = true
            setProject(value)
          }}
        />
        <div className="r-field">
          <label htmlFor="rfq-note">Note for the filing session (optional)</label>
          <input
            id="rfq-note"
            className="r-input"
            type="text"
            maxLength={NOTE_MAX}
            value={note}
            placeholder="For example: useful for the next project review"
            onChange={(event) => {
              touched.current = true
              setNote(event.target.value)
            }}
          />
        </div>
      </div>
    </Dialog>
  )
}
