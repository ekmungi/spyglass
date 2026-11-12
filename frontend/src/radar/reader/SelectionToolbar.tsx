// SelectionToolbar: the small floating bar that appears over selected text in the reader, with
// Ask, Explain and Why is this so?.
import { useEffect, useState, type RefObject } from 'react'
import { attachQuote, queueSend } from '../assistant/assistStore'
import { getSelectionInfo, selectionRequest, toolbarPosition, type SelectionAction } from './selection'

interface Placement {
  text: string
  top: number
  left: number
  below: boolean
}

/**
 * Watches selections inside `docRef` and positions itself inside the scrolling `layerRef`.
 * `watchKey` changes when the document element is replaced, so listeners re-attach.
 */
export function SelectionToolbar({
  docRef,
  layerRef,
  watchKey,
}: {
  docRef: RefObject<HTMLElement | null>
  layerRef: RefObject<HTMLElement | null>
  watchKey: string
}) {
  const [placement, setPlacement] = useState<Placement | null>(null)

  useEffect(() => {
    const doc = docRef.current
    if (!doc) return
    const update = () => {
      const layer = layerRef.current
      const info = getSelectionInfo(window.getSelection(), doc)
      if (!info || !layer) {
        setPlacement(null)
        return
      }
      const box = layer.getBoundingClientRect()
      const position = toolbarPosition(info.rect, { top: box.top, left: box.left, width: box.width }, layer.scrollTop)
      setPlacement({ text: info.text, top: position.top, left: position.left, below: position.below })
    }
    // Wait a tick after mouseup so the browser has finalised the selection.
    const onPointerUp = () => setTimeout(update, 0)
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.shiftKey || event.key === 'Shift') update()
    }
    const onSelectionChange = () => {
      const selection = window.getSelection()
      if (!selection || selection.isCollapsed) setPlacement(null)
    }
    doc.addEventListener('mouseup', onPointerUp)
    doc.addEventListener('keyup', onKeyUp)
    document.addEventListener('selectionchange', onSelectionChange)
    return () => {
      doc.removeEventListener('mouseup', onPointerUp)
      doc.removeEventListener('keyup', onKeyUp)
      document.removeEventListener('selectionchange', onSelectionChange)
    }
  }, [docRef, layerRef, watchKey])

  if (!placement) return null

  const choose = (action: SelectionAction) => {
    const request = selectionRequest(action, placement.text)
    if (request.kind === 'quote') attachQuote('reader', request.text)
    else queueSend('reader', request.send)
    window.getSelection()?.removeAllRanges()
    setPlacement(null)
  }

  return (
    <div
      className={placement.below ? 'r-seltool r-seltool--below' : 'r-seltool'}
      role="toolbar"
      aria-label="Ask about the selected text"
      style={{ top: placement.top, left: placement.left }}
      // Keep the selection alive while clicking a button.
      onMouseDown={(event) => event.preventDefault()}
    >
      <button type="button" onClick={() => choose('ask')}>
        Ask
      </button>
      <button type="button" onClick={() => choose('explain')}>
        Explain
      </button>
      <button type="button" onClick={() => choose('why')}>
        Why is this so?
      </button>
    </div>
  )
}
