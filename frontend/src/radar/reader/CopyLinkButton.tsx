// CopyLinkButton: the reader bar's "Copy the link". After a copy the icon becomes a tick and the
// tooltip shows "Link copied" for two seconds; a failed copy says so in a toast.
import { useEffect, useState } from 'react'
import { IconButton, IconCopyLink, IconSelected, toast } from '../ui'

// How long the tick and "Link copied" stay after a copy (milliseconds).
const COPIED_MS = 2000

/** Copy `url` (an address already checked as a plain web address) to the clipboard on click. */
export function CopyLinkButton({ url }: { url: string }) {
  // The time of the last copy, so a second copy within the two seconds starts the wait again.
  const [copiedAt, setCopiedAt] = useState<number | null>(null)

  useEffect(() => {
    if (copiedAt === null) return
    const timer = setTimeout(() => setCopiedAt(null), COPIED_MS)
    return () => clearTimeout(timer)
  }, [copiedAt])

  const copy = async () => {
    try {
      if (!navigator.clipboard) throw new Error('No clipboard')
      await navigator.clipboard.writeText(url)
      setCopiedAt(Date.now())
    } catch {
      toast('Could not copy the link.', { tone: 'error' })
    }
  }

  const copied = copiedAt !== null
  return (
    <span className={`r-copylink${copied ? ' is-copied' : ''}`}>
      <IconButton
        label={copied ? 'Link copied' : 'Copy the link'}
        icon={copied ? <IconSelected size={18} /> : <IconCopyLink size={18} />}
        tooltipSide="bottom"
        onClick={() => void copy()}
      />
    </span>
  )
}
