// Open-brief view: back affordance, title, send-to-Claude, markdown body.
// The References / Also noticed tails render as collapsible panels
// below the narrative, and Recompose regenerates the brief in place.
// The narrative itself renders through BriefNarrative, which adds
// per-bullet grip selection; this component owns the selection Set. Launching a
// selection goes through a transient BriefSessionPopover instead of happening directly.
// The top-right action is one adaptive control —
// 0 selected launches the whole brief directly (onOpenClaude), >=1 selected opens
// the scoped BriefSessionPopover with a clear affordance — replacing the standalone
// "Send to Claude" button and BriefNarrative's now-removed selection bar.
import { ArrowLeft, Loader2, RefreshCw, X } from 'lucide-react'
import { useState } from 'react'
import * as api from '../lib/api'
import { bulletKey, parseBriefBullets } from '../lib/briefBullets'
import { parseCardIds } from '../lib/briefLinks'
import { splitBrief } from '../lib/briefSections'
import type { Brief } from '../lib/types'
import { BriefNarrative } from './BriefNarrative'
import { BriefSectionPanel } from './BriefSectionPanel'
import { BriefSessionPopover, type SelectedBullet } from './BriefSessionPopover'
import { ClaudeIcon } from './ClaudeIcon'
import { Markdown } from './workspace/Markdown'

// Seeds the spawned session with the brief-discussion workflow.
const BRIEF_PROMPT =
  "Use the spyglass skill: discuss today's Spyglass brief with me; its referenced cards are loaded."

interface Props {
  brief: Brief
  onBack: () => void
  // Hands the brief's referenced card ids + a seeded prompt to a Claude session.
  onOpenClaude: (cardIds: number[], prompt?: string) => void
  // Routes a clicked card:<id> markdown link to the workspace reader.
  onCardLink?: (id: number) => void
  // Receives the fresh brief after a successful recompose; the
  // parent swaps it into its open/list state so this view re-renders in place.
  onRecomposed?: (brief: Brief) => void
}

/** One open Daily Brief: rendered markdown with card: links plus actions.
 * The markdown splits at ## References: the narrative renders as before, the
 * References / Also noticed tails become collapsible panels. */
export function BriefReader({ brief, onBack, onOpenClaude, onCardLink, onRecomposed }: Props) {
  const [recomposing, setRecomposing] = useState(false)
  // Quiet inline notice for recompose outcomes (paused / failed).
  const [notice, setNotice] = useState<string | null>(null)
  // Selected bullet keys, owned here so the unified top-right control
  // and each bullet's grip read/update the same state.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // The bullets currently offered to the scope popover; null means closed.
  // Set by openSession, cleared when the popover closes.
  const [sessionBullets, setSessionBullets] = useState<SelectedBullet[] | null>(null)

  const sections = splitBrief(brief.markdown)
  const parsedNarrative = parseBriefBullets(sections.narrative)
  // Shared markdown styling for both tail panels.
  const mdStyle = { fontSize: 'var(--font-size-body)', lineHeight: 1.6 } as const

  const recompose = () => {
    setRecomposing(true)
    setNotice(null)
    api
      .recomposeBrief(brief.id)
      .then((fresh) => onRecomposed?.(fresh))
      .catch((err: Error) => setNotice(err.message))
      .finally(() => setRecomposing(false))
  }

  // Toggle one bullet's selection immutably (new Set, never mutate the current one).
  const toggleBullet = (key: string) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  // Open the scope popover for the given bullet keys: build the
  // SelectedBullet[] the popover needs (each bullet's loaded + related cards)
  // from the parsed narrative, and let the popover drive the actual onOpenClaude
  // launch (one session for every selected bullet).
  const openSession = (bulletKeys: string[]) => {
    const keySet = new Set(bulletKeys)
    const picked: SelectedBullet[] = []
    parsedNarrative.sections.forEach((section, sectionIndex) => {
      section.bullets.forEach((bullet, bulletIndex) => {
        const key = bulletKey(sectionIndex, bulletIndex)
        if (!keySet.has(key)) return
        picked.push({ key, cards: bullet.cards, related: bullet.related })
      })
    })
    setSessionBullets(picked)
  }

  // Launch a session from the popover, then clear the bullet selection: the pick has
  // served its purpose, so the control reverts to the whole-brief affordance (issue #6).
  // Only on launch -- backing out of the popover (Esc / backdrop / Close) leaves the
  // selection intact so the user can adjust and retry.
  const launchSession = (cardIds: number[], prompt?: string) => {
    onOpenClaude(cardIds, prompt)
    setSelected(new Set())
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Pinned action row (Back / Recompose / Open in Claude); the brief body
          scrolls below it so the controls stay out of the scroller. */}
      <div className="mb-3 flex flex-none items-center justify-between gap-2">
        <button
          type="button"
          className="inline-flex items-center gap-1 border border-border px-2.5 py-1 text-muted hover:text-ink"
          style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
          onClick={onBack}
        >
          <ArrowLeft size={13} /> Back to list
        </button>
        {/* Recompose outcome notice sits inline, left of the action buttons. */}
        <span className="ml-auto text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
          {notice}
        </span>
        <button
          type="button"
          className="inline-flex items-center gap-1 border border-border px-2.5 py-1 text-body hover:text-ink disabled:opacity-40"
          style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
          disabled={recomposing}
          onClick={recompose}
        >
          {recomposing ? (
            <>
              <Loader2 size={13} className="animate-spin" /> Recomposing…
            </>
          ) : (
            <>
              <RefreshCw size={13} /> Recompose
            </>
          )}
        </button>
        {selected.size === 0 ? (
          <button
            type="button"
            className="inline-flex h-[30px] items-center gap-1.5 border px-2.5 text-accent hover:bg-card"
            style={{
              borderRadius: 'var(--radius-control)',
              borderColor: 'color-mix(in srgb, var(--color-accent) 35%, var(--color-border))',
              background: 'color-mix(in srgb, var(--color-accent) 6%, transparent)',
              fontSize: 'var(--font-size-actions)',
            }}
            onClick={() => onOpenClaude(parseCardIds(brief.markdown), BRIEF_PROMPT)}
          >
            <ClaudeIcon size={15} /> Open in Claude
          </button>
        ) : (
          <div
            className="inline-flex h-[30px] items-center gap-1.5 border px-2.5 text-accent"
            style={{
              borderRadius: 'var(--radius-control)',
              borderColor: 'color-mix(in srgb, var(--color-accent) 35%, var(--color-border))',
              background: 'color-mix(in srgb, var(--color-accent) 6%, transparent)',
              fontSize: 'var(--font-size-actions)',
            }}
          >
            <button
              type="button"
              className="inline-flex items-center gap-1.5 hover:text-ink"
              onClick={() => openSession([...selected])}
            >
              <ClaudeIcon size={15} /> Open {selected.size} in Claude
            </button>
            <button
              type="button"
              aria-label="Clear selection"
              title="Clear selection"
              className="inline-flex items-center pl-1.5 text-muted hover:text-ink"
              style={{
                borderLeft: '1px solid color-mix(in srgb, var(--color-accent) 30%, var(--color-border))',
              }}
              onClick={() => setSelected(new Set())}
            >
              <X size={13} />
            </button>
          </div>
        )}
      </div>
      <div className="tab-scroll">
      <div
        className="border border-border bg-card p-6"
        style={{ borderRadius: 'var(--radius-card)' }}
      >
        <h2 className="mb-4 font-bold text-ink" style={{ fontSize: 'var(--font-size-headline)' }}>
          {brief.title}
        </h2>
        <BriefNarrative
          parsed={parsedNarrative}
          selected={selected}
          onToggleBullet={toggleBullet}
          onCardLink={onCardLink}
        />
        {sections.references !== null && (
          <BriefSectionPanel title="References" defaultOpen>
            {/* The shared Markdown component keeps card: links routable inside the panel. */}
            <Markdown className="text-body" style={mdStyle} onCardLink={onCardLink}>
              {sections.references}
            </Markdown>
          </BriefSectionPanel>
        )}
        {sections.alsoNoticed !== null && (
          <BriefSectionPanel title={`Also noticed (${sections.alsoCount})`} defaultOpen={false}>
            <Markdown className="text-body" style={mdStyle} onCardLink={onCardLink}>
              {sections.alsoNoticed}
            </Markdown>
          </BriefSectionPanel>
        )}
      </div>
      </div>
      {sessionBullets && (
        <BriefSessionPopover
          bullets={sessionBullets}
          onOpenClaude={launchSession}
          onClose={() => setSessionBullets(null)}
        />
      )}
    </div>
  )
}
