// "Similar articles" list under the reader: nearest neighbours by embedding cosine.
// The service returns scored results (best first); the score shows subtly.
import { useEffect, useState } from 'react'
import * as api from '../../lib/api'
import type { ScoredCard } from '../../lib/types'

/** Fetch + list articles similar to cardId; clicking one opens it via onOpen. */
export function SimilarPanel({ cardId, onOpen }: { cardId: number; onOpen?: (id: number) => void }) {
  const [items, setItems] = useState<ScoredCard[]>([])
  useEffect(() => {
    let stale = false
    api.getSimilar(cardId).then((r) => !stale && setItems(r)).catch(() => !stale && setItems([]))
    return () => { stale = true }
  }, [cardId])
  if (items.length === 0) return null
  return (
    <div className="mt-4 border-t border-border pt-3">
      <div className="mb-2 font-semibold uppercase tracking-wider text-accent" style={{ fontSize: 'var(--font-size-meta)' }}>
        Similar articles
      </div>
      <ul className="flex flex-col gap-1">
        {items.map((c) => (
          <li key={c.id} className="flex items-baseline gap-2">
            <button
              type="button"
              onClick={() => onOpen?.(c.id)}
              className="text-left text-body hover:text-accent"
              style={{ fontSize: 'var(--font-size-meta)' }}
            >
              {c.title}
            </button>
            {/* Cosine score, muted so it reads as a hint rather than a metric. */}
            <span className="shrink-0 text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
              {c.score.toFixed(2)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
