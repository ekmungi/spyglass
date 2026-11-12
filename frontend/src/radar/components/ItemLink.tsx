// ItemLink: the one click target that opens an item in the reader. A real link (middle-click and
// copy-link still work) whose plain click goes through the router and marks the item opened.
import type { ReactNode } from 'react'
import { buildHash, navigate } from '../router'
import { markOpened } from '../state/itemState'

export interface ItemLinkProps {
  id: number
  className?: string
  children: ReactNode
  onOpen?: () => void
  /** Hover text, used by compact rows to show why the story matters without expanding. */
  title?: string
}

/** Open the reader for item `id` on click; carries data-row-open so j/k can focus it. */
export function ItemLink({ id, className, children, onOpen, title }: ItemLinkProps) {
  return (
    <a
      href={buildHash({ name: 'item', id })}
      className={className}
      title={title}
      data-row-open=""
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
        event.preventDefault()
        markOpened(id)
        onOpen?.()
        navigate({ name: 'item', id })
      }}
    >
      {children}
    </a>
  )
}
