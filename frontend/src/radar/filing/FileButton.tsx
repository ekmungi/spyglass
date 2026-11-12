// FileButton: the reader's "File in vault" control. One click adds the item to the To file queue
// (nothing opens, nothing is written); the small menu beside it offers "File as…". Once queued the
// button reads "Waiting to be filed" and offers to remove the item or change its choices. An item
// already filed shows "Filed". Both labels reserve the width of the longer one, so the change of
// state fades in place instead of pushing the top bar about.
import { useState } from 'react'
import type { FiledInfo } from '../api/types'
import { queueItem, unqueueItem, useFiling } from '../state/filingState'
import { Button, IconButton, IconExpand, IconFiled, IconFileInVault, IconQueued, Menu } from '../ui'
import { FileAsDialog } from './FileAsDialog'
import './filing.css'

export interface FileButtonProps {
  itemId: number
  /** The service's mark for the item: "waiting" while it is in the queue. */
  filing: 'waiting' | null | undefined
  /** Where the item was filed, once it has been. */
  filed: FiledInfo | null | undefined
}

const ADD_LABEL = 'File in vault'
const WAITING_LABEL = 'Waiting to be filed'

/**
 * A label that is as wide as the longer of the two states' labels: the other text is laid out
 * invisibly by CSS from `data-other` (not part of the text or of the accessible name).
 */
function SteadyLabel({ text, other, className }: { text: string; other: string; className?: string }) {
  return (
    <span className={['r-filebtn__label', className ?? ''].filter(Boolean).join(' ')} data-other={other}>
      {text}
    </span>
  )
}

/** The split control for the reader's top bar. */
export function FileButton({ itemId, filing, filed }: FileButtonProps) {
  const waiting = useFiling(itemId, filing) === 'waiting'
  const [dialog, setDialog] = useState<'add' | 'change' | null>(null)
  // A state reached by the reader's own click fades in; the first paint of the bar does not.
  const [touched, setTouched] = useState(false)
  const stateClass = `r-filebtn__state${touched ? ' r-appear' : ''}`

  if (filed) {
    return (
      <Button variant="quiet" size="sm" disabled icon={<IconFiled size={14} />} title={`Filed in ${filed.project || 'your vault'}: ${filed.path}`}>
        Filed
      </Button>
    )
  }

  return (
    <span className="r-filebtn">
      {waiting ? (
        <span key="waiting" className={stateClass}>
          <Menu
            label="Filing queue options"
            items={[
              {
                id: 'remove',
                label: 'Remove from the queue',
                onSelect: () => {
                  setTouched(true)
                  void unqueueItem(itemId)
                },
              },
              { id: 'change', label: 'Change…', onSelect: () => setDialog('change') },
            ]}
            trigger={
              <Button variant="quiet" size="sm" className="r-filebtn__queued" icon={<IconQueued size={14} />} aria-label={WAITING_LABEL} title="This item is in your filing queue">
                <SteadyLabel text={WAITING_LABEL} other={ADD_LABEL} className="r-filebtn__long" />
                <span className="r-filebtn__short" aria-hidden="true">
                  To file
                </span>
                <IconExpand size={14} />
              </Button>
            }
          />
        </span>
      ) : (
        <span key="add" className={stateClass}>
          <Button
            variant="quiet"
            size="sm"
            icon={<IconFileInVault size={14} />}
            onClick={() => {
              setTouched(true)
              void queueItem(itemId)
            }}
            title="Add to your filing queue; nothing is written yet"
          >
            <SteadyLabel text={ADD_LABEL} other={WAITING_LABEL} />
          </Button>
          <Menu
            label="More ways to file"
            items={[{ id: 'file-as', label: 'File as…', onSelect: () => setDialog('add') }]}
            trigger={<IconButton label="More ways to file" icon={<IconExpand size={14} />} tooltipSide="bottom" />}
          />
        </span>
      )}
      {dialog && <FileAsDialog itemId={itemId} changing={dialog === 'change'} onClose={() => setDialog(null)} />}
    </span>
  )
}
