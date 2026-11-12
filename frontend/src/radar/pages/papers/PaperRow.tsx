// PaperRow: one ranked paper: title, authors and date, how it relates to the reader, and its actions.
import type { PaperResult } from '../../api/types'
import { plainText } from '../../lib/plainText'
import { safeHttpUrl } from '../../lib/safeUrl'
import { Button } from '../../ui'
import { formatDay } from '../sources/format'
import { formatAuthors } from './authors'

export interface PaperRowProps {
  paper: PaperResult
  /** The feed item this paper is (already, or after "Add to my feed"), or null when it is not in the feed. */
  itemId: number | null
  adding: boolean
  /** A plain-language reason the last "Add to my feed" failed. */
  addError: string | null
  onAdd: (paper: PaperResult) => void
}

/** One result row. Open goes to the reader when the paper is already an item, otherwise to the paper's page. */
export function PaperRow({ paper, itemId, adding, addError, onAdd }: PaperRowProps) {
  const meta = [formatAuthors(paper.authors), formatDay(paper.published)].filter(Boolean).join(' · ')
  // Only plain web addresses become links; anything else is shown as text.
  const pageUrl = safeHttpUrl(paper.url)
  const pdfUrl = safeHttpUrl(paper.pdf_url)
  return (
    <li className="rpp-row">
      <h3 className="rpp-title">{plainText(paper.title)}</h3>
      {meta && <p className="r-meta">{meta}</p>}
      {!pageUrl && itemId === null && paper.url && <p className="r-meta">{paper.url}</p>}
      {paper.why && (
        <p className="rpp-why">
          <span className="rpp-label">How it relates to you</span>
          {paper.why}
        </p>
      )}
      {paper.signal && <p className="r-meta">{paper.signal}</p>}
      {paper.abstract && (
        <details className="rpp-abstract">
          <summary>Abstract</summary>
          <p>{paper.abstract}</p>
        </details>
      )}
      <div className="rpp-actions">
        {itemId !== null ? (
          <a className="r-btn r-btn--secondary r-btn--sm" href={`#/item/${itemId}`}>
            Open
          </a>
        ) : (
          pageUrl && (
            <a className="r-btn r-btn--secondary r-btn--sm" href={pageUrl} target="_blank" rel="noopener noreferrer">
              Open
            </a>
          )
        )}
        {pdfUrl && (
          <a className="r-btn r-btn--quiet r-btn--sm" href={pdfUrl} target="_blank" rel="noopener noreferrer">
            PDF
          </a>
        )}
        {itemId === null ? (
          <Button variant="quiet" size="sm" disabled={adding} onClick={() => onAdd(paper)}>
            {adding ? 'Adding…' : 'Add to my feed'}
          </Button>
        ) : (
          <span className="r-meta rpp-added">{paper.item_id === null ? 'Added to your feed' : 'In your feed'}</span>
        )}
      </div>
      {addError && (
        <p className="r-error-text" role="alert">
          {addError}
        </p>
      )}
    </li>
  )
}
