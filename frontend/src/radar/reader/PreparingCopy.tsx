// PreparingCopy: the one view shown from the click on an item until its reader copy is ready, both
// while the item itself loads and while the server reports the copy as pending, so the message never
// changes between the two. The icon is static; the placeholder bars below it already move, and they
// follow the reduced-motion setting.
import { Button, IconPreparing, Skeleton } from '../ui'
import { useAfterDelay } from './useAfterDelay'

/** The fixed wording of the wait, also used by the Help page and the test guide. */
export const PREPARING_MESSAGE = 'Preparing a clean copy and a summary of this article. The first time takes a few seconds.'

export interface PreparingCopyProps {
  /** True once the wait is clearly longer than usual. */
  slow?: boolean
  /** Starts the wait again; shown as Try again only when `slow`. */
  onRetry?: () => void
  /** Hold the icon and message back for this long; the bars and the status region show at once. */
  delayMs?: number
}

/** The icon and message, an optional "taking longer" line with Try again, and the placeholder bars. */
export function PreparingCopy({ slow = false, onRetry, delayMs = 0 }: PreparingCopyProps) {
  const shown = useAfterDelay(delayMs)
  return (
    // The status region exists from the start, so a screen reader announces the message when it appears.
    <div className="r-preparing" role="status" aria-live="polite">
      {shown && (
        <p className="r-preparing__message">
          <IconPreparing size={18} className="r-preparing__icon" />
          <span>{PREPARING_MESSAGE}</span>
        </p>
      )}
      {shown && slow && (
        <p className="r-preparing__slow">
          <span>This is taking longer than usual.</span>
          {onRetry && (
            <Button variant="quiet" size="sm" onClick={onRetry}>
              Try again
            </Button>
          )}
        </p>
      )}
      <Skeleton lines={5} height={15} />
      <Skeleton lines={4} height={15} />
    </div>
  )
}
