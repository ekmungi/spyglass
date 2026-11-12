// ReaderBody: the document part of the reader, by kind (article, email, note, paper, pdf, video)
// and status (ok, pending, failed, or no readable copy yet). A failed copy or a subscriber-only
// preview carries a hint on bringing the page in from the reader's own browser.
import { useState, type Ref } from 'react'
import { itemPdfUrl, refreshReader } from '../api/client'
import { errorMessage } from '../api/errors'
import { describeReaderFailure } from '../lib/readerFailure'
import { isMockMode } from '../api/transport'
import type { ItemDetail } from '../api/types'
import { BringInHint } from '../import/BringInHint'
import { openExternal, safeHttpUrl } from '../lib/safeUrl'
import { PDF_PLACEHOLDER_HTML } from '../mock/images'
import { Button, IconOpenOriginal, IconPartial, IconRetry, Skeleton } from '../ui'
import { embedUrl } from './embed'
import { Prose } from './Prose'

/** The address used by the built-in PDF viewer (a placeholder page in sample mode). */
function pdfSource(id: number): string {
  return isMockMode() ? PDF_PLACEHOLDER_HTML : itemPdfUrl(id)
}

/** The reason a page could not be read, in one plain sentence with the technical text under Details. */
function FailureReason({ reason }: { reason: string }) {
  const failure = describeReaderFailure(reason)
  return (
    <>
      <p className="r-meta">{failure.message}</p>
      <details className="r-reader-unavailable__details">
        <summary>Details</summary>
        <p className="r-meta">{failure.detail}</p>
      </details>
    </>
  )
}

/** The failed / missing state: the reason, Retry, and Open original. */
function Unavailable({ detail, onRefreshed }: { detail: ItemDetail; onRefreshed: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const failed = detail.reader?.status === 'failed'
  const original = safeHttpUrl(detail.url)
  const retry = async () => {
    setBusy(true)
    setError(null)
    try {
      await refreshReader(detail.id)
      onRefreshed()
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="r-reader-unavailable" role={failed ? 'alert' : undefined}>
      <p className="r-reader-unavailable__title">{failed ? 'Spyglass could not make a clean copy of this page.' : 'There is no readable copy of this page yet.'}</p>
      {failed && detail.reader?.error && <FailureReason reason={detail.reader.error} />}
      {failed && <BringInHint url={detail.url} showOpen={false} />}
      <div className="r-reader-unavailable__actions">
        <Button variant="secondary" icon={<IconRetry size={14} />} onClick={retry} disabled={busy}>
          {busy ? 'Trying again…' : failed ? 'Retry' : 'Make a readable copy'}
        </Button>
        {original ? (
          <Button variant="quiet" icon={<IconOpenOriginal size={14} />} onClick={() => openExternal(original)}>
            Open original
          </Button>
        ) : (
          // An address that is not a plain web address is shown as text, never linked or opened.
          detail.url && <span className="r-meta">{detail.url}</span>
        )}
      </div>
      {error && <p className="r-error-text">{error}</p>}
    </div>
  )
}

export interface ReaderBodyProps {
  detail: ItemDetail
  showPdf: boolean
  proseRef: Ref<HTMLDivElement>
  onRefreshed: () => void
}

/** The document under the summary block. */
export function ReaderBody({ detail, showPdf, proseRef, onRefreshed }: ReaderBodyProps) {
  const reader = detail.reader
  if (reader?.status === 'pending') {
    return (
      <div className="r-reader-pending" role="status" aria-live="polite">
        <p className="r-meta">Preparing a clean copy of this page…</p>
        <Skeleton lines={5} height={15} />
        <Skeleton lines={4} height={15} />
      </div>
    )
  }
  if (!reader || reader.status === 'failed') return <Unavailable detail={detail} onRefreshed={onRefreshed} />
  if (reader.partial) {
    return (
      <>
        <p className="rim-notice">
          <IconPartial size={16} className="rim-notice__icon" />
          <span>{reader.notice || 'Only a preview is available; the site limits this article to subscribers.'}</span>
        </p>
        <BringInHint url={detail.url} />
        <ReaderDocument detail={detail} showPdf={showPdf} proseRef={proseRef} />
      </>
    )
  }
  return <ReaderDocument detail={detail} showPdf={showPdf} proseRef={proseRef} />
}

/** A readable document by kind: the article, a PDF in the viewer, or a video with its text. */
function ReaderDocument({ detail, showPdf, proseRef }: Omit<ReaderBodyProps, 'onRefreshed'>) {
  const reader = detail.reader
  if (!reader) return null
  const pdfFrame = <iframe className="r-pdf" src={pdfSource(detail.id)} title={`PDF of ${detail.headline}`} />
  if (reader.kind === 'pdf') {
    return (
      <>
        {reader.html && <Prose ref={proseRef} html={reader.html} />}
        {pdfFrame}
      </>
    )
  }
  if (reader.kind === 'paper' && showPdf) return pdfFrame
  if (reader.kind === 'video') {
    const player = embedUrl(reader.alt_url ?? detail.url)
    return (
      <>
        {player && (
          <div className="r-video">
            <iframe
              src={player}
              title={`Video: ${detail.headline}`}
              allow="accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen"
              allowFullScreen
              sandbox="allow-scripts allow-same-origin allow-presentation"
              referrerPolicy="strict-origin-when-cross-origin"
            />
          </div>
        )}
        <Prose ref={proseRef} html={reader.html} />
      </>
    )
  }
  return <Prose ref={proseRef} html={reader.html} />
}
