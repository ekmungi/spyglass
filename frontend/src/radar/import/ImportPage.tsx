// ImportPage: the small "Add this page to Spyglass?" window that the Send to Spyglass button opens.
// The page arrives by postMessage (then it is parked with the service) or, after the button's form
// fallback, as a token in the address. Nothing is added until the reader presses Add.
import { useCallback, useEffect, useRef, useState } from 'react'
import { acceptStagedImport, discardStagedImport, getStagedImport, stageImport } from '../api/client'
import { errorMessage } from '../api/errors'
import type { RadarItem, StagedImport } from '../api/types'
import { clearResourceCache, useResource } from '../hooks/useResource'
import { buildHash, navigate } from '../router'
import { Button, Skeleton } from '../ui'
import { ACK_MESSAGE } from './bookmarklet'
import { REPLACE_REFUSED_MESSAGE, isAnswerableOrigin, readPageMessage, senderMismatchLine, stageErrorMessage, type PageMessage } from './messages'
import './import.css'

/** After this long without a page, the window explains what may have gone wrong. */
export const SLOW_AFTER_MS = 10_000

type Outcome = { kind: 'adding' } | { kind: 'added'; item: RadarItem } | { kind: 'discarded' } | { kind: 'failed'; message: string }

/**
 * Listen for the page from the window that opened this one. Only the first message with the right
 * shape and size, from the opener, from a real http(s) origin, is taken; it is answered to that
 * sender alone, and every later message is ignored.
 */
function useIncomingPage(listening: boolean, onPage: (page: PageMessage, origin: string) => void): void {
  const taken = useRef(false)
  const handler = useRef(onPage)
  useEffect(() => {
    handler.current = onPage
  })
  useEffect(() => {
    if (!listening) return
    const listener = (event: MessageEvent) => {
      if (taken.current || !event.source || event.source !== window.opener) return
      if (!isAnswerableOrigin(event.origin)) return
      const page = readPageMessage(event.data)
      if (!page) return
      taken.current = true
      ;(event.source as Window).postMessage({ type: ACK_MESSAGE }, event.origin)
      handler.current(page, event.origin)
    }
    window.addEventListener('message', listener)
    return () => window.removeEventListener('message', listener)
  }, [listening])
}

/** Close this window when a script opened it; otherwise there is nothing to close. */
function closeWindow(): void {
  window.close()
}

/** Waiting for the page: a calm line, and after a while what to do if nothing comes. */
function Waiting({ staging, error }: { staging: boolean; error: string | null }) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => setSlow(true), SLOW_AFTER_MS)
    return () => window.clearTimeout(timer)
  }, [])
  if (error) return <p className="r-error-text" role="alert">{error}</p>
  return (
    <div role="status" aria-live="polite">
      <p className="rim-lede">{staging ? 'Receiving the page…' : 'Waiting for the page from your browser…'}</p>
      {slow && !staging && (
        <p className="r-meta">
          Nothing has arrived. Some sites stop pages from talking to other windows. Save the page from your browser (Ctrl+S) and use Add a file in
          Spyglass instead.
        </p>
      )}
    </div>
  )
}

/**
 * How long the Add button stays disabled after the preview appears. A page that opened this window
 * itself must not be able to catch a click (or double-click) meant for something else on its own page.
 */
export const ARM_AFTER_MS = 700

/** The confirmation: where the page is from, in full, what it says, and the two choices. */
function Confirm({ preview, busy, onAdd, onDiscard }: { preview: StagedImport; busy: boolean; onAdd: () => void; onDiscard: () => void }) {
  const mismatch = senderMismatchLine(preview.sender, preview.host, preview.sender_matches)
  // The service refuses this too; saying it here means the reader is not offered a button that fails.
  const blocked = preview.replace_refused
  const readable = preview.word_count > 0
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => setArmed(true), ARM_AFTER_MS)
    return () => window.clearTimeout(timer)
  }, [])
  return (
    <>
      <h1 className="rim-title">Add this page to Spyglass?</h1>
      <p className="rim-host">{preview.host}</p>
      <p className="rim-url">{preview.url}</p>
      {preview.title && <h2 className="rim-page-title">{preview.title}</h2>}
      {readable ? (
        <p className="rim-excerpt">{preview.excerpt}</p>
      ) : (
        <p className="r-meta">No readable text was found in this page, so there is nothing to add.</p>
      )}
      <p className="r-meta">
        {readable && `About ${preview.word_count.toLocaleString()} words. `}
        {preview.replaces_existing && !blocked && 'You already have this item; adding replaces its reader copy.'}
      </p>
      {mismatch && <p className="rim-sender" role="note">{mismatch}</p>}
      {blocked && <p className="rim-refused" role="note">{REPLACE_REFUSED_MESSAGE}</p>}
      <div className="rim-actions">
        {!blocked && (
          <Button variant="primary" onClick={onAdd} disabled={busy || !readable || !armed}>
            {busy ? 'Adding…' : 'Add to Spyglass'}
          </Button>
        )}
        <Button variant="quiet" onClick={onDiscard} disabled={busy}>
          Discard
        </Button>
      </div>
    </>
  )
}

/** The import window. `token` names a page waiting for confirmation; `error` is a fixed code. */
export function ImportPage({ token, error }: { token?: string; error?: string }) {
  const [staging, setStaging] = useState(false)
  const [stageError, setStageError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const key = token ? `import:${token}` : null
  const preview = useResource<StagedImport>(key, (signal) => getStagedImport(token ?? '', signal))

  useEffect(() => {
    document.title = 'Add to Spyglass'
  }, [])

  const receive = useCallback(async (page: PageMessage, origin: string) => {
    setStaging(true)
    try {
      const staged = await stageImport({ ...page, sender: origin })
      navigate({ name: 'import', token: staged.token }, { replace: true })
    } catch (cause) {
      setStageError(errorMessage(cause))
    } finally {
      setStaging(false)
    }
  }, [])
  useIncomingPage(!token && !error, receive)

  const add = async () => {
    if (!token) return
    setOutcome({ kind: 'adding' })
    try {
      const item = await acceptStagedImport(token)
      if (key) clearResourceCache(key)
      setOutcome({ kind: 'added', item })
    } catch (cause) {
      setOutcome({ kind: 'failed', message: errorMessage(cause) })
    }
  }

  const discard = async () => {
    if (!token) return
    try {
      await discardStagedImport(token)
    } catch {
      // Already gone (expired or used): either way nothing was added.
    }
    if (key) clearResourceCache(key)
    setOutcome({ kind: 'discarded' })
  }

  let body
  if (outcome?.kind === 'added') {
    const open = () => window.open(`${window.location.pathname}${buildHash({ name: 'item', id: outcome.item.id })}`, '_blank', 'noopener')
    body = (
      <div role="status">
        <p className="rim-lede">Added. It will be judged in the next collection.</p>
        <div className="rim-actions">
          <Button variant="primary" onClick={open}>Open in Spyglass</Button>
          <Button variant="quiet" onClick={closeWindow}>Close this window</Button>
        </div>
      </div>
    )
  } else if (outcome?.kind === 'discarded') {
    body = (
      <div role="status">
        <p className="rim-lede">Discarded. Nothing was added.</p>
        <div className="rim-actions">
          <Button variant="quiet" onClick={closeWindow}>Close this window</Button>
        </div>
      </div>
    )
  } else if (error) {
    body = <p className="r-error-text" role="alert">{stageErrorMessage(error)}</p>
  } else if (!token) {
    body = <Waiting staging={staging} error={stageError} />
  } else if (preview.data) {
    body = (
      <>
        <Confirm preview={preview.data} busy={outcome?.kind === 'adding'} onAdd={add} onDiscard={discard} />
        {outcome?.kind === 'failed' && <p className="r-error-text" role="alert">{outcome.message}</p>}
      </>
    )
  } else if (preview.error) {
    body = <p className="r-error-text" role="alert">{errorMessage(preview.error)}</p>
  } else {
    body = (
      <div aria-busy="true" aria-label="Loading the page">
        <Skeleton lines={4} />
      </div>
    )
  }

  return (
    <main className="rim-window" id="r-main-content">
      <p className="rim-brand">Spyglass</p>
      {body}
    </main>
  )
}
