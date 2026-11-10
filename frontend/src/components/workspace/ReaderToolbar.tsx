// Compact icon-first reader toolbar: item actions | relevance dot +
// category chip (net-change indicators) | primary Send to Claude.
// Per-card notes are dormant.
import { Archive, ChevronDown, Globe, Search, Tag, Telescope, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { RELEVANCE_LEVELS, relevanceColor } from '../../lib/relevance'
import type { CardData, CategoryInfo, Feedback, Relevance } from '../../lib/types'
import { ClaudeIcon } from '../ClaudeIcon'
import { NewCategoryInput } from './CategoryChips'
import { ThumbsControl } from './ThumbsControl'

interface Props {
  card: CardData
  categories: CategoryInfo[]
  onArchive: () => void
  // Accepts null to clear the override and revert to the AI value.
  onSetRelevance: (relevance: Relevance | null) => void
  onSetCategory: (name: string) => void
  onCreateCategory: (name: string) => void
  onSend: () => void
  // Optional per-item actions; buttons hidden when not provided.
  onOpenExternal?: () => void
  onDelete?: () => void
  // Optional thumbs feedback; buttons hidden when not provided.
  onFeedback?: (next: Feedback) => void
  // Enter explore mode seeded on this card; hidden when not provided.
  onExplore?: () => void
  // Seed a Claude session to research new similar articles on the web.
  onResearch?: () => void
}

const ICON =
  'inline-flex size-[30px] items-center justify-center border border-border text-body hover:border-accent hover:text-accent'

/** Floating menu anchored under its trigger; closes on any outside click. */
function PopMenu({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const handle = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [onClose])
  return (
    <div
      ref={ref}
      className="absolute bottom-full left-0 z-20 mb-1 min-w-[140px] border border-border bg-card p-1 shadow-lg"
      style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
    >
      {children}
    </div>
  )
}

/** One row, three clusters separated by thin dividers. */
export function ReaderToolbar({
  card,
  categories,
  onArchive,
  onSetRelevance,
  onSetCategory,
  onCreateCategory,
  onSend,
  onOpenExternal,
  onDelete,
  onFeedback,
  onExplore,
  onResearch,
}: Props) {
  const [menu, setMenu] = useState<'relevance' | 'category' | null>(null)
  const [addingCategory, setAddingCategory] = useState(false)
  // Two-step inline confirm for permanent delete; Escape resets it.
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const close = () => {
    setMenu(null)
    setAddingCategory(false)
  }

  const relTitle = `relevance: ${card.relevance ?? 'unjudged'}${
    card.relevance_override ? ' (you set)' : ''
  }`
  const menuItem =
    'flex w-full items-center gap-2 px-2 py-1.5 text-left text-body hover:bg-surface'

  return (
    <div className="mt-4 flex items-center gap-2.5 border-t border-border pt-3">
      <div className="flex items-center gap-1.5">
        {onFeedback && (
          <ThumbsControl feedback={card.feedback} onFeedback={onFeedback} btnClass={ICON} iconSize={15} />
        )}
        <button type="button" aria-label="Archive" title="Archive" className={ICON}
          style={{ borderRadius: 'var(--radius-control)' }} onClick={onArchive}>
          <Archive size={15} />
        </button>
        {onExplore && (
          <button type="button" aria-label="Explore similar" title="Explore similar articles in the workspace" className={ICON}
            style={{ borderRadius: 'var(--radius-control)' }} onClick={onExplore}>
            <Telescope size={15} />
          </button>
        )}
        {onResearch && (
          <button type="button" aria-label="Research on the web" title="Research new similar articles on the web via Claude" className={ICON}
            style={{ borderRadius: 'var(--radius-control)' }} onClick={onResearch}>
            <Search size={15} />
          </button>
        )}
        {onOpenExternal && (
          <button type="button" aria-label="Open in browser" title="Open in browser" className={ICON}
            style={{ borderRadius: 'var(--radius-control)' }} onClick={onOpenExternal}>
            <Globe size={15} />
          </button>
        )}
        {onDelete && (
          confirmingDelete ? (
            <>
              <button type="button" aria-label="Confirm delete" title="Confirm delete"
                className="inline-flex items-center border border-red-500 px-1.5 py-0.5 text-red-500 hover:bg-red-50"
                style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
                onClick={() => { onDelete(); setConfirmingDelete(false) }}>
                Delete?
              </button>
              <button type="button" aria-label="Cancel delete" title="Cancel delete"
                className={`${ICON}`}
                style={{ borderRadius: 'var(--radius-control)' }}
                onClick={() => setConfirmingDelete(false)}>
                ✕
              </button>
            </>
          ) : (
            <button type="button" aria-label="Delete" title="Delete" className={ICON}
              style={{ borderRadius: 'var(--radius-control)' }} onClick={() => setConfirmingDelete(true)}>
              <Trash2 size={15} />
            </button>
          )
        )}
      </div>
      <span className="h-5 w-px bg-border" />
      <div className="flex items-center gap-1.5">
        <span className="relative">
          <button
            type="button"
            aria-label={relTitle}
            title={relTitle}
            className={`${ICON} ${card.relevance_override ? 'override border-accent ring-2 ring-accent/35' : ''}`}
            style={{ borderRadius: 'var(--radius-control)' }}
            onClick={() => setMenu(menu === 'relevance' ? null : 'relevance')}
          >
            <span
              className="size-[11px] rounded-full"
              style={
                card.relevance === null
                  ? // Unjudged: a visible hollow dot, not a border-on-border ghost.
                    { border: '2px dashed var(--color-muted)' }
                  : { backgroundColor: relevanceColor(card.relevance) }
              }
            />
          </button>
          {menu === 'relevance' && (
            <PopMenu onClose={close}>
              {RELEVANCE_LEVELS.map((level) => (
                <button
                  key={level.value}
                  type="button"
                  className={`${menuItem} ${card.relevance === level.value ? 'font-semibold text-accent' : ''}`}
                  style={{ borderRadius: 'var(--radius-control)' }}
                  onClick={() => {
                    onSetRelevance(level.value)
                    close()
                  }}
                >
                  <span
                    className="size-[9px] rounded-full"
                    style={{ backgroundColor: relevanceColor(level.value) }}
                  />
                  {level.label}
                  {level.value === card.relevance_ai ? ' (AI)' : ''}
                </button>
              ))}
              <div className="mt-0.5 border-t border-border pt-1">
                <button
                  type="button"
                  aria-label="Clear relevance override"
                  className={`${menuItem} text-muted`}
                  style={{ borderRadius: 'var(--radius-control)' }}
                  onClick={() => {
                    onSetRelevance(null)
                    close()
                  }}
                >
                  Clear
                </button>
              </div>
            </PopMenu>
          )}
        </span>
        <span className="relative">
          <button
            type="button"
            className={`inline-flex items-center gap-1.5 border px-2 py-1.5 ${
              card.category_override
                ? 'override border-accent text-accent'
                : 'border-border text-body hover:border-accent'
            }`}
            style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-meta)' }}
            onClick={() => setMenu(menu === 'category' ? null : 'category')}
          >
            <Tag size={11} /> {card.category ?? 'Uncategorized'} <ChevronDown size={11} />
          </button>
          {menu === 'category' && (
            <PopMenu onClose={close}>
              {[...categories].sort((a, b) => a.name.localeCompare(b.name)).map((c) => (
                <button
                  key={c.name}
                  type="button"
                  className={`${menuItem} ${card.category === c.name ? 'font-semibold text-accent' : ''}`}
                  style={{ borderRadius: 'var(--radius-control)' }}
                  onClick={() => {
                    onSetCategory(c.name)
                    close()
                  }}
                >
                  {c.name}
                  {c.name === card.category_ai ? ' (AI)' : ''}
                </button>
              ))}
              <div className="mt-0.5 border-t border-border pt-1">
                {addingCategory ? (
                  <NewCategoryInput onCreate={onCreateCategory} onDone={close} />
                ) : (
                  <button
                    type="button"
                    className={`${menuItem} text-accent`}
                    style={{ borderRadius: 'var(--radius-control)' }}
                    onClick={() => setAddingCategory(true)}
                  >
                    + New category
                  </button>
                )}
              </div>
            </PopMenu>
          )}
        </span>
      </div>
      <button
        type="button"
        className="ml-auto inline-flex items-center gap-1.5 bg-accent px-3 py-1.5 text-card"
        style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
        onClick={onSend}
      >
        <ClaudeIcon size={14} /> Send to Claude
      </button>
    </div>
  )
}
