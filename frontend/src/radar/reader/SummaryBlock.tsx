// SummaryBlock: where the item was filed (when it was), the reader's own note (for a link they sent)
// with a quiet "Open in Claude Code…" beside it, the key points as a short list, then "Why it
// matters to you", above the document. Lines that only repeat the document's opening (a paper's
// abstract) are left out here so the abstract is not shown twice.
import type { ItemDetail } from '../api/types'
import { openClaudeDialog } from '../claude/claudeStore'
import { formatDate } from '../lib/format'
import { Button } from '../ui'
import { repeatsDocumentStart } from './summaryText'

/** "Filed · Imaging AI · 12 Nov 2026", with the note's path beneath in small muted text. */
function FiledLine({ filed }: { filed: NonNullable<ItemDetail['filed']> }) {
  const when = formatDate(filed.at)
  return (
    <p className="r-summary__filed">
      <span>{['Filed', filed.project || 'your vault', when].filter(Boolean).join(' · ')}</span>
      <span className="r-summary__filed-path">{filed.path}</span>
    </p>
  )
}

/** Key points and the why line; falls back to the feed snippet; renders nothing when all are empty. */
export function SummaryBlock({ detail }: { detail: ItemDetail }) {
  const html = detail.reader?.status === 'ok' ? detail.reader.html : null
  const points = detail.key_points.filter((point) => point.trim() && !repeatsDocumentStart(point, html))
  const snippet = detail.summary && detail.summary !== detail.why && !repeatsDocumentStart(detail.summary, html) ? detail.summary : null
  const fallback = !points.length ? snippet : null
  // The item detail carries the reader's note as `user_note`; older shapes kept it on the state or the item.
  const note = (detail.user_note ?? detail.state.note ?? detail.note ?? '').trim()
  const filed = detail.filed ?? null
  const sentByReader = detail.state.from_user
  if (!points.length && !detail.why && !fallback && !note && !filed && !sentByReader) return null
  return (
    <section className="r-summary" aria-label="Summary">
      {filed && <FiledLine filed={filed} />}
      {note && (
        <p className="r-summary__note">
          <span className="r-summary__note-label">Your note:</span> {note}
        </p>
      )}
      {sentByReader && (
        <p className="r-summary__action">
          <Button variant="quiet" size="sm" onClick={() => openClaudeDialog({ itemId: detail.id })}>
            Open in Claude Code…
          </Button>
        </p>
      )}
      {points.length > 0 && (
        <ul className="r-summary__points">
          {points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      )}
      {fallback && <p className="r-summary__snippet">{fallback}</p>}
      {detail.why && (
        <div className="r-summary__why">
          <h2 className="r-summary__why-label">Why it matters to you</h2>
          <p>{detail.why}</p>
        </div>
      )}
    </section>
  )
}
