// ReaderHead: the reader's title and the line under it, which joins the byline with the source, the
// date and the reading time ("Ada Lovelace · Example Site · 12 Nov 2026 · 10 min read").
import type { ItemDetail } from '../api/types'
import { formatDate, sentByYou } from '../lib/format'
import { plainText } from '../lib/plainText'
import { readingLabel } from './readingLabel'

/** The reader's title: the headline the reader clicked, except for papers, which keep their own title. */
function readerTitle(detail: ItemDetail): string {
  const isPaper = detail.kind === 'paper' || detail.reader?.kind === 'paper' || detail.reader?.kind === 'pdf'
  return plainText(isPaper ? detail.reader?.title || detail.title || detail.headline : detail.headline)
}

/** "Publication · 12 Nov 2026 · 6 min read" (with "Sent by you …" for captured items). */
function readerMeta(detail: ItemDetail): string {
  return [
    detail.reader?.site || detail.origin,
    formatDate(detail.published_at),
    readingLabel(detail.reader),
    detail.state.from_user ? sentByYou(detail.state.captured_via) : null,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** The title, then the byline and the meta joined by " · " (the meta alone without a byline). */
export function ReaderHead({ detail }: { detail: ItemDetail }) {
  const line = [detail.reader?.byline, readerMeta(detail)].filter(Boolean).join(' · ')
  return (
    <header className="r-reader__head">
      <h1 className="r-reader__title">{readerTitle(detail)}</h1>
      {line && <p className="r-reader__byline">{line}</p>}
    </header>
  )
}
