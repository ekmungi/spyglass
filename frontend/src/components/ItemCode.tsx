// An item's code (#1042, its card id), copied with one click so the user can point the linked
// Claude session at it. Clicks stop here so a row does not also open.
import { useState } from 'react'
import { copyText } from '../lib/link'

export function ItemCode({ id }: { id: number }) {
  const [copied, setCopied] = useState(false)
  const code = `#${id}`
  return (
    <button
      type="button"
      className="rounded border border-border px-1 font-mono text-muted hover:border-accent hover:text-accent"
      style={{ fontSize: '10.5px', lineHeight: 1.5 }}
      title={`Copy ${code} to point Claude at this item`}
      aria-label={`Copy ${code}`}
      onClick={(event) => {
        event.stopPropagation()
        void copyText(code).then((ok) => {
          if (!ok) return
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }}
    >
      {copied ? 'Copied' : code}
    </button>
  )
}
