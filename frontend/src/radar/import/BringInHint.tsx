// The reader's hint for a page Spyglass could not read in full (a failed copy or a subscriber-only
// preview): read it in the browser and bring it in with the Send to Spyglass button.
import { openExternal, safeHttpUrl } from '../lib/safeUrl'
import { buildHash, navigate, type Route } from '../router'
import { Button, IconOpenOriginal } from '../ui'
import './import.css'

const SETUP: Route = { name: 'settings', section: 'bring-in' }

/** One calm line, "Open original" (unless the page already offers it) and "How to set this up". */
export function BringInHint({ url, showOpen = true }: { url: string; showOpen?: boolean }) {
  const original = safeHttpUrl(url)
  return (
    <div className="rim-hint">
      <p className="rim-hint__line">You can read it in your browser and bring it in: open the original, then use your Send to Spyglass button.</p>
      <div className="rim-hint__actions">
        {showOpen && original && (
          <Button variant="quiet" size="sm" icon={<IconOpenOriginal size={14} />} onClick={() => openExternal(original)}>
            Open original
          </Button>
        )}
        <a
          href={buildHash(SETUP)}
          onClick={(event) => {
            event.preventDefault()
            navigate(SETUP)
          }}
        >
          How to set this up
        </a>
      </div>
    </div>
  )
}
