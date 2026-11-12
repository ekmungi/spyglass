// ReaderPage (#/item/<id>): opened over the page you came from. Top bar, title, summary block,
// the clean document, related items, and the selection toolbar that hands passages to the assistant.
import { useEffect, useRef, useState } from 'react'
import { getItem } from '../api/client'
import { errorMessage } from '../api/errors'
import type { ItemDetail } from '../api/types'
import { setAssistTarget } from '../assistant/assistStore'
import { ItemLink } from '../components/ItemLink'
import { isTypingTarget } from '../hooks/useListKeys'
import { useResource } from '../hooks/useResource'
import { plainText } from '../lib/plainText'
import { goBack } from '../router'
import { markOpened } from '../state/itemState'
import { Button, EmptyState, SectionHeading, Skeleton } from '../ui'
import { ReaderBody } from './ReaderBody'
import { ReaderTopBar } from './ReaderTopBar'
import { SelectionToolbar } from './SelectionToolbar'
import { SummaryBlock } from './SummaryBlock'
import { useReaderSignals } from './useReaderSignals'
import './reader.css'

const PENDING_POLL_MS = 3000
const PENDING_MAX_POLLS = 20

/** The reader's title: the headline the reader clicked, except for papers, which keep their own title. */
function readerTitle(detail: ItemDetail): string {
  const isPaper = detail.kind === 'paper' || detail.reader?.kind === 'paper' || detail.reader?.kind === 'pdf'
  return plainText(isPaper ? detail.reader?.title || detail.title || detail.headline : detail.headline)
}

/** Related items at the end of the document (embedding neighbours). */
function Related({ detail }: { detail: ItemDetail }) {
  if (!detail.related.length) return null
  return (
    <section className="r-related" aria-labelledby="r-related-title">
      <SectionHeading id="r-related-title" as="h2">
        Related
      </SectionHeading>
      <ul className="r-rows">
        {detail.related.slice(0, 5).map((item) => (
          <li key={item.id} className="r-related__row">
            <ItemLink id={item.id} className="r-related__link">
              <span className="r-headline">{plainText(item.headline)}</span>
              <span className="r-meta">{[item.origin, item.section_label].filter(Boolean).join(' · ')}</span>
            </ItemLink>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The reader for one item. */
export function ReaderPage({ id }: { id: number }) {
  const { data: detail, error, loading, reload } = useResource(`item:${id}`, (signal) => getItem(id, signal))
  const layerRef = useRef<HTMLDivElement>(null)
  const proseRef = useRef<HTMLDivElement>(null)
  const [showPdf, setShowPdf] = useState(false)
  const polls = useRef(0)

  useReaderSignals(id)

  useEffect(() => {
    markOpened(id)
    layerRef.current?.focus({ preventScroll: true })
  }, [id])

  useEffect(() => {
    setAssistTarget({ kind: 'item', id, title: plainText(detail?.headline) })
  }, [id, detail?.headline])

  // Poll while the server is still building the reader document.
  const pending = detail?.reader?.status === 'pending'
  useEffect(() => {
    if (!pending || polls.current >= PENDING_MAX_POLLS) return
    const timer = setTimeout(() => {
      polls.current += 1
      reload()
    }, PENDING_POLL_MS)
    return () => clearTimeout(timer)
  }, [pending, detail, reload])

  // Esc returns to where the reader came from (unless typing, or a menu/dialog takes it first).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && !isTypingTarget(event.target)) goBack()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  let content
  if (detail) {
    content = (
      <>
        <ReaderTopBar detail={detail} showPdf={showPdf} onTogglePdf={() => setShowPdf((value) => !value)} />
        <article className={`r-reader r-reader--${detail.reader?.kind ?? 'article'}`}>
          <header className="r-reader__head">
            <h1 className="r-reader__title">{readerTitle(detail)}</h1>
            {detail.reader?.byline && <p className="r-reader__byline">{detail.reader.byline}</p>}
          </header>
          <SummaryBlock detail={detail} />
          <ReaderBody detail={detail} showPdf={showPdf} proseRef={proseRef} onRefreshed={reload} />
          <Related detail={detail} />
        </article>
        <SelectionToolbar docRef={proseRef} layerRef={layerRef} watchKey={`${detail.id}:${detail.reader?.status}:${showPdf}`} />
      </>
    )
  } else if (loading) {
    content = (
      <div className="r-reader" role="status" aria-label="Loading the article">
        <Skeleton width="30%" height={12} />
        <div style={{ height: 24 }} />
        <Skeleton width="90%" height={34} />
        <div style={{ height: 32 }} />
        <Skeleton lines={6} height={15} />
      </div>
    )
  } else {
    content = (
      <div className="r-reader">
        <EmptyState
          title="This item could not be opened"
          body={errorMessage(error)}
          action={
            <div style={{ display: 'flex', gap: 8 }}>
              <Button variant="primary" onClick={reload}>
                Try again
              </Button>
              <Button onClick={() => goBack()}>Back</Button>
            </div>
          }
        />
      </div>
    )
  }

  return (
    <div ref={layerRef} className="r-layer r-layer--reader" tabIndex={-1} role="region" aria-label="Reader">
      {content}
    </div>
  )
}
