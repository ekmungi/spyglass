// FollowDialog: "Follow more like this". Reads an article (or a web address), shows what could be
// followed as a short checklist, creates a tracked topic for each ticked line, and says how it went
// line by line. The same dialog serves the reader's Follow button and the Add link dialog.
import './follow.css'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createTrack, suggestTracksForItem, suggestTracksForUrl } from '../api/client'
import { ApiError, errorMessage } from '../api/errors'
import type { TrackSuggestResponse } from '../api/types'
import { navigate } from '../router'
import { Button, Dialog, Skeleton, toast } from '../ui'
import { followSummary, mostSpecific, suggestionKey } from './followLogic'
import { SimilarList } from './SimilarList'
import { SuggestionList, type RowState } from './SuggestionList'

/** What the suggestions are read from: a stored item, or a web address that is read first. */
export type FollowSource = { kind: 'item'; id: number } | { kind: 'url'; url: string }

export interface FollowDialogProps {
  open: boolean
  source: FollowSource
  onClose: () => void
}

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: TrackSuggestResponse }

/** The dialog; nothing is requested until it is open, and closing cancels a request still running. */
export function FollowDialog({ open, source, onClose }: FollowDialogProps) {
  if (!open) return null
  return <FollowSession source={source} onClose={onClose} />
}

/** One open session: the request, the ticks, the per-line results and the closing toast. */
function FollowSession({ source, onClose }: { source: FollowSource; onClose: () => void }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set())
  const [rows, setRows] = useState<Readonly<Record<string, RowState>>>({})
  const [busy, setBusy] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)
  const stats = useRef({ followed: 0, found: 0 })
  const closed = useRef(false)
  const toasted = useRef(false)
  const onCloseRef = useRef(onClose)
  const sourceKey = source.kind === 'item' ? `item:${source.id}` : `url:${source.url}`

  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    const controller = new AbortController()
    const request =
      source.kind === 'item' ? suggestTracksForItem(source.id, controller.signal) : suggestTracksForUrl(source.url, controller.signal)
    request.then(
      (data) => {
        if (controller.signal.aborted) return
        const first = mostSpecific(data.suggestions)
        setTicked(new Set(first ? [suggestionKey(first)] : []))
        setLoad({ status: 'ready', data })
      },
      (cause: unknown) => {
        if (!controller.signal.aborted) setLoad({ status: 'error', message: errorMessage(cause) })
      },
    )
    return () => controller.abort()
    // The source is fixed for the life of a session; `attempt` re-runs the request after an error.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt, sourceKey])

  useEffect(() => {
    if (load.status === 'ready') bodyRef.current?.querySelector<HTMLInputElement>('input:not(:disabled)')?.focus()
  }, [load.status])

  /** Say what was followed, once, with a way to see it. */
  const announce = useCallback(() => {
    if (toasted.current || stats.current.followed === 0) return
    toasted.current = true
    toast(followSummary(stats.current.followed, stats.current.found), { action: { label: 'See topics', onClick: () => navigate({ name: 'watch' }) } })
  }, [])

  const close = useCallback(() => {
    closed.current = true
    announce()
    onCloseRef.current()
  }, [announce])

  const toggle = (key: string) =>
    setTicked((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const data = load.status === 'ready' ? load.data : null
  const openLines = (data?.suggestions ?? []).filter((line) => {
    const key = suggestionKey(line)
    return !line.already_followed && rows[key]?.status !== 'done' && rows[key]?.status !== 'existing'
  })
  const chosen = openLines.filter((line) => ticked.has(suggestionKey(line)))

  /** Create a track for each ticked line, in parallel, and report each line on its own. */
  const followSelected = async () => {
    if (!data || chosen.length === 0) return
    const fromItem = source.kind === 'item' ? source.id : data.item?.id
    setBusy(true)
    setRows((current) => ({ ...current, ...Object.fromEntries(chosen.map((line) => [suggestionKey(line), { status: 'following' } as RowState])) }))
    const outcomes = await Promise.all(
      chosen.map(async (line) => {
        const key = suggestionKey(line)
        try {
          const created = await createTrack({ label: line.label, query: line.query, section: line.section, kind: line.kind, ...(fromItem ? { from_item_id: fromItem } : {}) })
          return { key, state: { status: 'done' } as RowState, found: created.new_items ?? 0, followed: 1 }
        } catch (cause) {
          // A 409 means it was followed already (perhaps in another tab): not a failure.
          if (cause instanceof ApiError && cause.status === 409) return { key, state: { status: 'existing' } as RowState, found: 0, followed: 0 }
          return { key, state: { status: 'failed', error: errorMessage(cause) } as RowState, found: 0, followed: 0 }
        }
      }),
    )
    stats.current = {
      followed: stats.current.followed + outcomes.reduce((sum, outcome) => sum + outcome.followed, 0),
      found: stats.current.found + outcomes.reduce((sum, outcome) => sum + outcome.found, 0),
    }
    setRows((current) => ({ ...current, ...Object.fromEntries(outcomes.map((outcome) => [outcome.key, outcome.state])) }))
    setTicked((current) => new Set([...current].filter((key) => !outcomes.some((outcome) => outcome.key === key && outcome.state.status !== 'failed'))))
    setBusy(false)
    if (outcomes.every((outcome) => outcome.state.status !== 'failed')) {
      if (closed.current) announce()
      else close()
    }
  }

  const failed = Object.values(rows).some((row) => row.status === 'failed')
  const anyFollowed = Object.values(rows).some((row) => row.status === 'done')
  const footer =
    load.status === 'ready' ? (
      <>
        <Button variant="quiet" onClick={close}>
          {anyFollowed || failed ? 'Close' : 'Cancel'}
        </Button>
        <Button variant="primary" disabled={busy || chosen.length === 0} onClick={() => void followSelected()}>
          {busy ? 'Following…' : failed ? 'Try again' : 'Follow selected'}
        </Button>
      </>
    ) : load.status === 'error' ? (
      <>
        <Button variant="quiet" onClick={close}>
          Close
        </Button>
        <Button variant="primary" onClick={() => setAttempt((value) => value + 1)}>
          Try again
        </Button>
      </>
    ) : (
      <Button variant="quiet" onClick={close}>
        Cancel
      </Button>
    )

  return (
    <Dialog open onClose={close} title="Follow more like this" footer={footer}>
      <div ref={bodyRef} className="rf-body">
        {load.status === 'loading' && (
          <div className="rf-wait" role="status" aria-busy="true">
            <p className="rf-wait__line">{source.kind === 'item' ? 'Reading the article to suggest what to follow…' : 'Reading the link to suggest what to follow…'}</p>
            <Skeleton lines={4} height={16} />
          </div>
        )}
        {busy && (
          <p className="r-meta rf-intro" role="status">
            Running the first search for each topic. This can take a few seconds.
          </p>
        )}
        {load.status === 'error' && (
          <p className="r-error-text" role="alert">
            {load.message}
          </p>
        )}
        {data && (
          <div className="r-appear">
            {data.mode === 'basic' && <p className="r-meta rf-intro">Basic suggestions; the AI service was not available.</p>}
            {data.suggestions.length > 0 ? (
              <>
                <p className="r-meta rf-intro">Spyglass searches for each one every day. Choose what you want to keep up with.</p>
                <SuggestionList suggestions={data.suggestions} ticked={ticked} rows={rows} disabled={busy} onToggle={toggle} />
              </>
            ) : (
              <p className="r-meta rf-intro">Nothing obvious to follow in this article.</p>
            )}
            <SimilarList items={data.similar} onOpen={close} />
          </div>
        )}
      </div>
    </Dialog>
  )
}
