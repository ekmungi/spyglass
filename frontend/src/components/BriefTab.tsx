// Brief tab: the MVP front door -- a list of Daily Briefs, a generate-now
// action, and the open-brief reader (BriefReader).
import { Loader2, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import * as api from '../lib/api'
import type { Brief, BriefSummary } from '../lib/types'
import { BriefReader } from './BriefReader'

interface Props {
  // Hands card ids + a seeded prompt to a Claude session (App.openInClaude).
  onOpenClaude: (cardIds: number[], prompt?: string) => void
  // Routes a clicked card:<id> link inside a brief to the workspace reader.
  onCardLink?: (id: number) => void
}

/** Human window like "Jun 30 – Jul 1, 2026"; collapses same-day windows. */
function formatWindow(fromIso: string, untilIso: string): string {
  const from = new Date(fromIso)
  const until = new Date(untilIso)
  if (isNaN(from.getTime()) || isNaN(until.getTime())) {
    return ''
  }
  const day = { month: 'short', day: 'numeric' } as const
  const fromStr = from.toLocaleDateString('en-US', day)
  const untilStr = until.toLocaleDateString('en-US', day)
  const range = fromStr === untilStr ? fromStr : `${fromStr} – ${untilStr}`
  return `${range}, ${until.getFullYear()}`
}

/** "5 articles, 3 also noticed" -- the featured article count plus the low-relevance
 * tail (the brief's "Also noticed" section). Names the second number instead of the
 * opaque "+3 more" so the counts read clearly. */
function formatCounts(brief: BriefSummary): string {
  const articles = `${brief.item_count} article${brief.item_count === 1 ? '' : 's'}`
  return brief.low_count > 0 ? `${articles}, ${brief.low_count} also noticed` : articles
}

/** The Brief tab: newest-first list of briefs, generate-now, and the reader. */
export function BriefTab({ onOpenClaude, onCardLink }: Props) {
  // null = initial load in flight; [] = loaded, none exist yet.
  const [briefs, setBriefs] = useState<BriefSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<Brief | null>(null)
  const [generating, setGenerating] = useState(false)
  // Quiet inline notice for generate outcomes (empty / paused / failed).
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    api.getBriefs().then(setBriefs).catch((err: Error) => setError(err.message))
  }, [])

  const openBrief = (id: number) => {
    api.getBrief(id).then(setOpen).catch((err: Error) => setError(err.message))
  }

  const generate = () => {
    setGenerating(true)
    setNotice(null)
    api
      .generateBrief()
      .then((result) => {
        // Generate composes EVERY due publish-day, returning light summaries
        // (no markdown) under { composed, status, held } -- not a single brief. Prepend
        // the fresh summaries newest-first and open the newest by fetching it in full.
        if (result.composed.length > 0) {
          setBriefs((current) => [...result.composed, ...(current ?? [])])
          openBrief(result.composed[0].id)
          if (result.held > 0) {
            setNotice(`Composed ${result.composed.length}; ${result.held} more held for the next run.`)
          }
        } else if (result.held > 0) {
          // Nothing composed, but a day WAS due and its bucket paused (e.g. a heavy day
          // the partition gate can't cleanly summarize). Say so honestly instead of the
          // misleading "nothing to brief".
          setNotice(
            `${result.held} day${result.held === 1 ? '' : 's'} held — too many items to compose right now; it retries automatically on the next refresh.`,
          )
        } else {
          setNotice('Nothing new to brief.')
        }
      })
      .catch((err: Error) => setNotice(err.message))
      .finally(() => setGenerating(false))
  }

  if (open) {
    return (
      <BriefReader
        brief={open}
        onBack={() => setOpen(null)}
        onOpenClaude={onOpenClaude}
        onCardLink={onCardLink}
        onRecomposed={(fresh) => {
          // Swap the recomposed brief in place: the open reader
          // re-renders with the fresh markdown and the list entry follows.
          setOpen(fresh)
          setBriefs((current) =>
            current === null ? current : current.map((b) => (b.id === fresh.id ? fresh : b)),
          )
        }}
      />
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Pinned generate-now row; the brief list scrolls below it. */}
      <div className="mb-3 flex flex-none items-center justify-between gap-2">
        {/* Generate outcome notice sits inline, left of the button. */}
        <span className="text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
          {notice}
        </span>
        <button
          type="button"
          className="inline-flex items-center gap-1 border border-border px-2.5 py-1 text-body hover:text-ink disabled:opacity-40"
          style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
          disabled={generating}
          onClick={generate}
        >
          {generating ? (
            <>
              <Loader2 size={13} className="animate-spin" /> Generating…
            </>
          ) : (
            <>
              <Sparkles size={13} /> Generate now
            </>
          )}
        </button>
      </div>
      <div className="tab-scroll">
      {error && <p className="text-accent">{error}</p>}
      {briefs === null && !error && <p className="text-muted">Loading briefs…</p>}
      {briefs !== null && briefs.length === 0 && !error && (
        <p className="text-muted">
          No briefs yet. The Daily Brief composes itself automatically after each daily
          refresh — or generate one now to brief today&apos;s items.
        </p>
      )}
      {briefs !== null && briefs.length > 0 && (
        <ul className="flex flex-col gap-2">
          {briefs.map((brief) => (
            <li key={brief.id}>
              <button
                type="button"
                className="w-full border border-border bg-card p-4 text-left hover:border-accent"
                style={{ borderRadius: 'var(--radius-card)' }}
                onClick={() => openBrief(brief.id)}
              >
                <div className="font-semibold text-ink" style={{ fontSize: 'var(--font-size-body)' }}>
                  {brief.title}
                </div>
                <div className="mt-1 text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
                  {formatWindow(brief.covers_from, brief.covers_until)} · {formatCounts(brief)}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
      </div>
    </div>
  )
}
