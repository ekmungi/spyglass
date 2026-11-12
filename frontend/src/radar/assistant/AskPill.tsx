// AskPill: keeps the assistant reachable while a page is scrolled. Today has an "Ask about today"
// button in its masthead; once that button has scrolled out of view, a compact pill with the same
// label appears at the top-right of the column and opens the panel. It hides while the panel is
// open. The pill is only hidden, never removed, and takes no room in the page, so showing it moves
// nothing. (The Feed needs no pill: its Ask button sits in the filter bar, which stays in view.)
import { Button, IconAsk } from '../ui'
import './assistant.css'

export interface AskPillProps {
  /** The same words as the button it stands in for. */
  label: string
  shown: boolean
  onClick: () => void
}

/** The pill, stuck to the top-right of the scrolling column. Hidden means invisible and unfocusable. */
export function AskPill({ label, shown, onClick }: AskPillProps) {
  return (
    <div className="r-askpill-slot">
      <Button
        variant="secondary"
        size="sm"
        className="r-askpill"
        icon={<IconAsk size={14} />}
        data-shown={shown ? 'true' : 'false'}
        aria-hidden={shown ? undefined : true}
        tabIndex={shown ? 0 : -1}
        onClick={onClick}
      >
        {label}
      </Button>
    </div>
  )
}
