// Category management: the user owns a small, closed set. Add with +, remove with x.
// New items are filed into these buckets and the AI never invents new labels.
import { useEffect, useState } from 'react'
import * as api from '../lib/api'
import type { CategoryInfo } from '../lib/types'
import { RecategorizePanel } from './RecategorizePanel'

/** A single category chip: name, item count, and an x to remove it. */
function CategoryChip({ cat, onRemove }: { cat: CategoryInfo; onRemove: (name: string) => void }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 border border-border bg-canvas px-2 py-1 text-body"
      style={{ borderRadius: 'var(--radius-control)' }}
    >
      <span>{cat.name}</span>
      <span className="text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
        {cat.count}
      </span>
      <button
        type="button"
        aria-label={`Remove ${cat.name}`}
        className="text-muted hover:text-accent"
        onClick={() => onRemove(cat.name)}
      >
        ×
      </button>
    </span>
  )
}

/** Managed-category editor: lists the closed set as chips with +/x controls. */
export function CategorySettingsSection() {
  const [cats, setCats] = useState<CategoryInfo[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [status, setStatus] = useState('')

  const load = () =>
    api
      .getCategories()
      .then((list) => setCats(Array.isArray(list) ? list : []))
      .catch(() => setStatus('categories unavailable'))

  useEffect(() => {
    load()
  }, [])

  const add = () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setAdding(false)
      return
    }
    api
      .createCategory(trimmed)
      .then(() => {
        setName('')
        setAdding(false)
        load()
      })
      .catch(() => setStatus('add failed'))
  }

  const remove = (target: string) => {
    // Removing a category re-buckets its items to Unsorted; confirm since it is not per-card.
    if (!window.confirm(`Remove "${target}"? Its items move to Unsorted.`)) {
      return
    }
    api.deleteCategory(target).then(load).catch(() => setStatus('remove failed'))
  }

  return (
    <div className="mt-6 border-t border-border pt-4" style={{ fontSize: 'var(--font-size-actions)' }}>
      <h3 className="mb-1 font-semibold text-ink" style={{ fontSize: 'var(--font-size-body)' }}>
        Categories
      </h3>
      <p className="mb-3 text-muted">
        A small set you own. New items are filed into these buckets; the AI never invents new ones.
        Removing one moves its items to Unsorted.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {(cats ?? []).map((cat) => (
          <CategoryChip key={cat.name} cat={cat} onRemove={remove} />
        ))}
        {adding ? (
          <input
            type="text"
            autoFocus
            aria-label="New category name"
            className="border border-border bg-canvas px-2 py-1 text-body"
            style={{ borderRadius: 'var(--radius-control)', width: '180px' }}
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') add()
              if (event.key === 'Escape') {
                setName('')
                setAdding(false)
              }
            }}
            onBlur={add}
          />
        ) : (
          <button
            type="button"
            aria-label="Add category"
            className="border border-border px-2.5 py-1 text-body hover:border-accent"
            style={{ borderRadius: 'var(--radius-control)' }}
            onClick={() => setAdding(true)}
          >
            +
          </button>
        )}
      </div>
      {status && <span className="mt-2 block text-muted">{status}</span>}
      {/* Recategorize: accepting a candidate adds a category + counts, so reload. */}
      <RecategorizePanel onAccepted={load} />
    </div>
  )
}
