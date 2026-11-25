// FileButton: the reader bar's "File in vault" icon button. One click adds the item to the To file
// queue (nothing opens, nothing is written); the small menu button beside it offers "File as…".
// Once queued the icon reads "Waiting to be filed" and its menu offers to remove the item or change
// its choices. An item already filed shows a disabled "Filed" icon. Each state is as wide as the
// others, so the change fades in place instead of pushing the bar about. Tooltips open downwards.
import { useState } from 'react'
import type { FiledInfo } from '../api/types'
import { queueItem, unqueueItem, useFiling } from '../state/filingState'
import { IconButton, IconExpand, IconFiled, IconFileInVault, IconQueued, Menu } from '../ui'
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

/** The split control for the reader's top bar. */
export function FileButton({ itemId, filing, filed }: FileButtonProps) {
  const waiting = useFiling(itemId, filing) === 'waiting'
  const [dialog, setDialog] = useState<'add' | 'change' | null>(null)
  // A state reached by the reader's own click fades in; the first paint of the bar does not.
  const [touched, setTouched] = useState(false)
  const stateClass = `r-filebtn__state${touched ? ' r-appear' : ''}`

  if (filed) {
    return <IconButton label={`Filed in ${filed.project || 'your vault'}`} icon={<IconFiled size={18} />} tooltipSide="bottom" disabled />
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
              <IconButton
                label={WAITING_LABEL}
                className="r-filebtn__queued"
                icon={
                  <>
                    <IconQueued size={18} />
                    <IconExpand size={14} />
                  </>
                }
                tooltipSide="bottom"
              />
            }
          />
        </span>
      ) : (
        <span key="add" className={stateClass}>
          <IconButton
            label={ADD_LABEL}
            icon={<IconFileInVault size={18} />}
            tooltipSide="bottom"
            onClick={() => {
              setTouched(true)
              void queueItem(itemId)
            }}
          />
          <Menu
            label="More ways to file"
            items={[{ id: 'file-as', label: 'File as…', onSelect: () => setDialog('add') }]}
            trigger={<IconButton label="More ways to file" size="sm" icon={<IconExpand size={14} />} tooltipSide="bottom" />}
          />
        </span>
      )}
      {dialog && <FileAsDialog itemId={itemId} changing={dialog === 'change'} onClose={() => setDialog(null)} />}
    </span>
  )
}
