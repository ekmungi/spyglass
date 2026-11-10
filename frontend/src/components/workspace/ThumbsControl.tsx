// Thumbs up/down feedback control, shared by the list row and reader toolbar.
// Tapping to select plays a one-shot "pop" (scale up then back) while the active
// highlight persists; clearing or scrolling a rated row back into view does not pop.
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import type { Feedback } from '../../lib/types'

interface Props {
  feedback: Feedback                   // current thumbs state
  onFeedback: (next: Feedback) => void // tap sets; re-tapping the active thumb clears (null)
  btnClass: string                     // base button class (caller supplies sizing/border)
  iconSize: number                     // lucide icon size in px
}

/** Two toggle buttons (up/down) with a tap-to-select pop animation. */
export function ThumbsControl({ feedback, onFeedback, btnClass, iconSize }: Props) {
  // Which direction was just tapped ON, so the pop plays once on the real click --
  // not on mount/scroll-in (rows remount under virtualization) and not on clear.
  const [popped, setPopped] = useState<Exclude<Feedback, null>>()

  const handle = (dir: 'up' | 'down') => {
    const next: Feedback = feedback === dir ? null : dir
    if (next !== null) setPopped(dir)
    onFeedback(next)
  }

  // Active thumb: filled icon in a semantic colour (up = ok green, down = out red) so a rated card is
  // unmistakable, not just a faint coral outline.
  const cls = (dir: 'up' | 'down') =>
    `${btnClass} ${feedback === dir ? (dir === 'up' ? 'text-ok' : 'text-out') : ''} ${
      popped === dir ? 'thumb-pop' : ''
    }`

  return (
    <>
      <button
        type="button"
        aria-label="Thumbs up"
        title="Good article"
        aria-pressed={feedback === 'up'}
        className={cls('up')}
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={() => handle('up')}
        onAnimationEnd={() => setPopped(undefined)}
      >
        <ThumbsUp size={iconSize} fill={feedback === 'up' ? 'currentColor' : 'none'} />
      </button>
      <button
        type="button"
        aria-label="Thumbs down"
        title="Bad article"
        aria-pressed={feedback === 'down'}
        className={cls('down')}
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={() => handle('down')}
        onAnimationEnd={() => setPopped(undefined)}
      >
        <ThumbsDown size={iconSize} fill={feedback === 'down' ? 'currentColor' : 'none'} />
      </button>
    </>
  )
}
