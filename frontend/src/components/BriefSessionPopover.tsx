// Transient Open-in-Claude popover: opens one Claude desktop
// session covering the selected brief bullets, lets the user review/drop
// related-card chips, and shows the prompt that will seed the session. The
// former One-per-bullet mode is gone: each desktop session asks to
// confirm its folder, so N bullets would have meant N dialogs. Not a routed view or docked panel — a dismissable
// overlay (Esc + backdrop close) rendered by BriefReader over the narrative.
import { useEffect, useState } from 'react'
import { ClaudeIcon } from './ClaudeIcon'

// One selected bullet's launch-relevant shape: its own loaded (non-removable)
// cards plus its related (removable) cards. Built by BriefReader from the
// parsed narrative + the selected bullet keys.
export interface SelectedBullet {
  key: string
  cards: { id: number; title: string }[]
  related: { id: number; title: string }[]
}

interface Props {
  bullets: SelectedBullet[]
  onOpenClaude: (cardIds: number[], prompt?: string) => void
  onClose: () => void
}

// How many related chips show before collapsing the rest behind "+N more
// related" (client-side reveal only — never a fresh fetch).
const RELATED_PREVIEW_COUNT = 2

/** Build the prompt seeding a session about the given card titles, matching the
 * voice of BriefReader's existing BRIEF_PROMPT constant. */
function buildPrompt(titles: string[]): string {
  const named = titles.join(', ')
  return `Use the spyglass skill: discuss these Spyglass items with me — ${named} — their cards are loaded.`
}

/** All titles referenced by a bullet (loaded + kept related), in a stable order,
 * for naming the seeded prompt. */
function bulletTitles(bullet: SelectedBullet, removed: Set<number>): string[] {
  const titles: string[] = []
  for (const card of bullet.cards) titles.push(card.title)
  for (const card of bullet.related) if (!removed.has(card.id)) titles.push(card.title)
  return titles
}

/** All kept ids for a bullet: its loaded cards (always) plus its non-removed
 * related cards. */
function bulletIds(bullet: SelectedBullet, removed: Set<number>): number[] {
  const ids: number[] = []
  for (const card of bullet.cards) ids.push(card.id)
  for (const card of bullet.related) if (!removed.has(card.id)) ids.push(card.id)
  return ids
}

/** The deduped title list across every selected bullet's kept cards, in first-
 * seen order — shared by the Combine launch and its prompt preview so the two
 * never drift apart. */
function combinedTitles(bullets: SelectedBullet[], removedFor: (key: string) => Set<number>): string[] {
  const titles: string[] = []
  for (const bullet of bullets) {
    for (const title of bulletTitles(bullet, removedFor(bullet.key))) {
      if (!titles.includes(title)) titles.push(title)
    }
  }
  return titles
}

/** One loaded-card chip: always included, never removable. */
function LoadedChip({ title }: { title: string }) {
  return (
    <span
      className="inline-flex items-center border border-border bg-card px-2 py-0.5 text-body"
      style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-meta)' }}
    >
      {title}
    </span>
  )
}

/** One related-card chip: removable via an inline "x" button. */
function RelatedChip({ title, onRemove }: { title: string; onRemove: () => void }) {
  return (
    <span
      className="inline-flex items-center gap-1 border border-border px-2 py-0.5 text-muted"
      style={{
        borderRadius: 'var(--radius-control)',
        fontSize: 'var(--font-size-meta)',
        background: 'color-mix(in srgb, var(--color-accent) 5%, transparent)',
      }}
    >
      {title}
      <button
        type="button"
        aria-label={`Remove ${title}`}
        title={`Remove ${title}`}
        className="text-muted hover:text-ink"
        onClick={onRemove}
      >
        ×
      </button>
    </span>
  )
}

/** One selected-bullet group: its loaded chips + related chips (with the +N
 * more reveal), scoped to this bullet's own `removed` set. */
function BulletGroup({
  bullet,
  removed,
  revealed,
  onRemoveRelated,
  onReveal,
}: {
  bullet: SelectedBullet
  removed: Set<number>
  revealed: boolean
  onRemoveRelated: (id: number) => void
  onReveal: () => void
}) {
  // Removed related cards drop out of the visible list entirely (toggle-off,
  // not re-addable in this task per the brief's "optional" re-add note).
  const kept = bullet.related.filter((card) => !removed.has(card.id))
  const shown = revealed ? kept : kept.slice(0, RELATED_PREVIEW_COUNT)
  const hiddenCount = kept.length - shown.length
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {bullet.cards.map((card) => (
        <LoadedChip key={card.id} title={card.title} />
      ))}
      {shown.map((card) => (
        <RelatedChip
          key={card.id}
          title={card.title}
          onRemove={() => onRemoveRelated(card.id)}
        />
      ))}
      {!revealed && hiddenCount > 0 && (
        <button
          type="button"
          className="text-accent hover:underline"
          style={{ fontSize: 'var(--font-size-meta)' }}
          onClick={onReveal}
        >
          +{hiddenCount} more related
        </button>
      )}
    </div>
  )
}

/** Transient popover: per-bullet chip groups, a seeded-prompt preview, and
 * Launch (one session for all selected bullets). Dismissable via Esc, backdrop click, or
 * after Launch fires. */
export function BriefSessionPopover({ bullets, onOpenClaude, onClose }: Props) {
  // Ids removed per bullet key — never mutated, only replaced wholesale.
  const [removedByBullet, setRemovedByBullet] = useState<Record<string, Set<number>>>({})
  // Bullet keys whose "+N more related" has been revealed.
  const [revealedKeys, setRevealedKeys] = useState<Set<string>>(new Set())

  // Esc dismisses, matching the other transient controls in this app.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const removedFor = (key: string): Set<number> => removedByBullet[key] ?? new Set<number>()

  // Toggle a related id off for one bullet, immutably (new Set, new record).
  const removeRelated = (key: string, id: number) => {
    setRemovedByBullet((current) => ({
      ...current,
      [key]: new Set(removedFor(key)).add(id),
    }))
  }

  const reveal = (key: string) => {
    setRevealedKeys((current) => new Set(current).add(key))
  }

  const launch = () => {
    const idSet = new Set<number>()
    for (const bullet of bullets) {
      for (const id of bulletIds(bullet, removedFor(bullet.key))) idSet.add(id)
    }
    onOpenClaude([...idSet], buildPrompt(combinedTitles(bullets, removedFor)))
    onClose()
  }

  return (
    <div
      data-testid="brief-session-popover-backdrop"
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 p-6"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label="Open in Claude"
        className="w-full max-w-lg border border-border bg-card p-5"
        style={{ borderRadius: 'var(--radius-card)' }}
        // Stop backdrop-click propagation so interacting with the popover itself
        // never dismisses it.
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-bold text-ink" style={{ fontSize: 'var(--font-size-body)' }}>
            Open in Claude
          </h3>
          <button
            type="button"
            aria-label="Close"
            title="Close"
            className="text-muted hover:text-ink"
            onClick={onClose}
          >
            ×
          </button>
        </div>

        {/* Per-bullet chip groups. */}
        <div className="mb-3 flex flex-col gap-2">
          {bullets.map((bullet) => (
            <BulletGroup
              key={bullet.key}
              bullet={bullet}
              removed={removedFor(bullet.key)}
              revealed={revealedKeys.has(bullet.key)}
              onRemoveRelated={(id) => removeRelated(bullet.key, id)}
              onReveal={() => reveal(bullet.key)}
            />
          ))}
        </div>

        {/* Seeded-prompt preview: names every kept title. */}
        <p
          className="mb-4 border border-border bg-surface p-2 text-muted"
          style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-meta)' }}
        >
          {buildPrompt(combinedTitles(bullets, removedFor))}
        </p>

        <div className="flex justify-end">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 border px-3 py-1.5 text-accent hover:bg-card"
            style={{
              borderRadius: 'var(--radius-control)',
              borderColor: 'color-mix(in srgb, var(--color-accent) 35%, var(--color-border))',
              background: 'color-mix(in srgb, var(--color-accent) 6%, transparent)',
              fontSize: 'var(--font-size-actions)',
            }}
            onClick={launch}
          >
            <ClaudeIcon size={15} /> Launch
          </button>
        </div>
      </div>
    </div>
  )
}
