// Archive tab: dismissed cards, each restorable. Nothing is ever deleted.
import { ArchiveRestore } from 'lucide-react'
import type { CardData } from '../lib/types'

interface Props {
  cards: CardData[]
  onUnarchive: (id: number) => void
}

/** Lists archived (dismissed) cards with an unarchive action. */
export function ArchivedTab({ cards, onUnarchive }: Props) {
  if (cards.length === 0) {
    return <p className="text-muted">Nothing archived. Dismissed cards appear here.</p>
  }
  return (
    <ul style={{ fontSize: 'var(--font-size-body)' }}>
      {cards.map((card) => (
        <li
          key={card.id}
          className="flex items-center gap-3 border-b border-border py-2"
        >
          <span className="min-w-20 font-semibold uppercase text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
            {card.source}
          </span>
          <a className="flex-1 text-ink" href={card.url} target="_blank" rel="noreferrer">
            {card.title}
          </a>
          <button
            type="button"
            aria-label={`Unarchive ${card.title}`}
            title="Unarchive"
            onClick={() => onUnarchive(card.id)}
            className="rounded p-1.5 text-muted hover:bg-card hover:text-accent"
          >
            <ArchiveRestore size={16} />
          </button>
        </li>
      ))}
    </ul>
  )
}
