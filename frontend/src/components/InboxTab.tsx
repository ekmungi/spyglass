// Inbox tab: the papers the user shared in their inbox Slack channel, each
// filed in the vault with a debrief by a Claude desktop session. "Process inbox" opens that
// session; the scheduled desktop task does the same at set times. The list refreshes
// itself while a run is going.
import { BookOpen, Inbox } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import * as api from '../lib/api'
import { formatAge } from '../lib/dates'
import { INBOX_PROMPT, runLine } from '../lib/inbox'
import type { InboxData } from '../lib/types'
import { ClaudeIcon } from './ClaudeIcon'
import { ItemCode } from './ItemCode'

const POLL_MS = 15000
// After Process inbox, keep looking for the run this long: the user still has to send the
// request in Claude desktop, and the run reports only when it starts.
const WATCH_MS = 30 * 60 * 1000

interface Props {
  // A conversation about a paper goes to the linked Claude session.
  onOpenClaude: (cardIds: number[], prompt?: string) => void
  // Processing the inbox is a job: it runs in its own new Claude session.
  onRunJob: (prompt: string) => void
}

export function InboxTab({ onOpenClaude, onRunJob }: Props) {
  const [data, setData] = useState<InboxData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [watchUntil, setWatchUntil] = useState(0)

  const load = useCallback(() => {
    api
      .getInbox()
      .then((next) => {
        setData(next)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Keep the list current while a Claude session is filing papers, and for a while after
  // Process inbox (the run starts only once the request is sent). Coming back to the window
  // refreshes it too, so a scheduled run that happened meanwhile shows at once.
  const running = data?.last_run?.status === 'running'
  useEffect(() => {
    if (!running && watchUntil === 0) return
    const timer = setInterval(() => {
      if (!running && Date.now() > watchUntil) {
        setWatchUntil(0)
        return
      }
      load()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [running, watchUntil, load])
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') load()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [load])

  const processInbox = () => {
    onRunJob(INBOX_PROMPT)
    setWatchUntil(Date.now() + WATCH_MS)
  }

  const openNote = (cardId: number) => {
    api.openInboxNote(cardId).catch((e: Error) => setError(e.message))
  }

  const channel = data?.channel ?? ''
  return (
    <div className="tab-scroll">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Inbox size={16} className="text-accent" aria-hidden />
        <div className="mr-auto min-w-0">
          <div className="font-semibold text-ink">
            {channel ? `Papers shared in #${channel}` : 'Paper inbox'}
          </div>
          <div className="text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
            {channel ? runLine(data?.last_run ?? null) : 'Set the inbox channel in Settings first.'}
          </div>
        </div>
        <button
          type="button"
          disabled={!channel}
          className="inline-flex items-center gap-1.5 border border-border px-3 py-1.5 text-accent hover:bg-card disabled:opacity-50"
          style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
          onClick={processInbox}
        >
          <ClaudeIcon size={15} /> Process inbox
        </button>
      </div>
      {error && <p className="mb-3 text-accent">{error}</p>}
      {data?.debriefs && data.debriefs.length > 0 && (
        <div
          className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-muted"
          style={{ fontSize: 'var(--font-size-meta)' }}
        >
          <span className="font-semibold text-ink">Run debriefs</span>
          {data.debriefs.map((d) => (
            <button
              key={d.run_id}
              type="button"
              className="inline-flex items-center gap-1 text-accent hover:underline"
              onClick={() => api.openRunDebrief(d.run_id).catch((e: Error) => setError(e.message))}
            >
              <BookOpen size={13} aria-hidden /> {formatAge(d.started_at)} · {d.papers} paper
              {d.papers === 1 ? '' : 's'}
            </button>
          ))}
        </div>
      )}
      {data && data.papers.length === 0 && (
        <p className="text-muted">
          Nothing here yet. Share a paper in the channel, then press Process inbox.
        </p>
      )}
      <ul className="flex flex-col gap-3">
        {data?.papers.map((paper) => (
          <li
            key={paper.entry_id}
            className="card-shadow border border-border bg-card px-4 py-3"
            style={{ borderRadius: 'var(--radius-card)' }}
          >
            <div className="flex items-start gap-2">
              <a
                href={paper.url}
                target="_blank"
                rel="noreferrer"
                className="mr-auto font-semibold text-ink hover:underline"
              >
                {paper.title}
              </a>
              <ItemCode id={paper.card_id} />
              <span className="text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
                {formatAge(paper.added_at)}
              </span>
            </div>
            {paper.message_text && (
              <p className="mt-1 text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
                You wrote: {paper.message_text}
              </p>
            )}
            <p className="mt-2 text-body">
              {paper.filed ? paper.summary || 'Filed.' : 'Being filed...'}
            </p>
            <div
              className="mt-2 flex flex-wrap items-center gap-3 text-muted"
              style={{ fontSize: 'var(--font-size-meta)' }}
            >
              {paper.filed && !paper.full_text && <span>Read from the abstract only</span>}
              {paper.shared > 1 && <span>Shared {paper.shared} times</span>}
              <span className="mr-auto" />
              {paper.note_path && (
                <button
                  type="button"
                  className="inline-flex items-center gap-1 text-accent hover:underline"
                  onClick={() => openNote(paper.card_id)}
                >
                  <BookOpen size={13} aria-hidden /> Open the debrief
                </button>
              )}
              <button
                type="button"
                className="inline-flex items-center gap-1 text-accent hover:underline"
                onClick={() =>
                  onOpenClaude([paper.card_id], 'Use the spyglass skill: discuss this paper with me.')
                }
              >
                <ClaudeIcon size={13} /> Discuss in Claude
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
