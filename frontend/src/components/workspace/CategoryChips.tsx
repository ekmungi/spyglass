// Category chip bar: All + non-empty categories + inline "+ New category".
// The ACTIVE chip exposes an inline rename (pencil). Empty categories are not
// shown as chips but persist in every dropdown.
import { Pencil } from 'lucide-react'
import { useState } from 'react'
import type { CategoryInfo } from '../../lib/types'

interface Props {
  categories: CategoryInfo[]
  active: string
  onSelect: (name: string) => void
  onCreate: (name: string) => void
  onRename: (oldName: string, newName: string) => void
}

/** Small inline input used to name a category; Enter commits, Escape cancels. */
export function NewCategoryInput({
  initial = '',
  label = 'New category name',
  onCreate,
  onDone,
}: {
  initial?: string
  label?: string
  onCreate: (name: string) => void
  onDone: () => void
}) {
  const [name, setName] = useState(initial)
  return (
    <input
      autoFocus
      aria-label={label}
      className="border border-accent bg-card px-2 py-0.5 text-body outline-none"
      style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
      value={name}
      onChange={(event) => setName(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && name.trim()) {
          onCreate(name.trim())
          onDone()
        }
        if (event.key === 'Escape') {
          onDone()
        }
      }}
    />
  )
}

/** Navigation chips over the list; squared rectangles. */
export function CategoryChips({ categories, active, onSelect, onCreate, onRename }: Props) {
  const [adding, setAdding] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const withItems = categories.filter((c) => c.count > 0)

  const chipClass = (selected: boolean) =>
    `border px-2.5 py-0.5 ${
      selected
        ? 'border-ink bg-ink text-canvas'
        : 'border-border bg-transparent text-body hover:text-ink'
    }`
  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      style={{ fontSize: 'var(--font-size-actions)' }}
    >
      <button
        type="button"
        className={chipClass(active === 'All')}
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={() => onSelect('All')}
      >
        All
      </button>
      {withItems.map((c) =>
        renaming && active === c.name ? (
          <NewCategoryInput
            key={c.name}
            initial={c.name}
            label={`Rename category ${c.name}`}
            onCreate={(newName) => onRename(c.name, newName)}
            onDone={() => setRenaming(false)}
          />
        ) : (
          <span
            key={c.name}
            className={`inline-flex items-center ${chipClass(active === c.name)}`}
            style={{ borderRadius: 'var(--radius-control)' }}
          >
            <button type="button" className="inherit" onClick={() => onSelect(c.name)}>
              {c.name} ({c.count})
            </button>
            {active === c.name && (
              <button
                type="button"
                aria-label={`Rename ${c.name}`}
                title={`Rename ${c.name}`}
                className="ml-1.5 opacity-70 hover:opacity-100"
                onClick={() => setRenaming(true)}
              >
                <Pencil size={11} />
              </button>
            )}
          </span>
        ),
      )}
      {adding ? (
        <NewCategoryInput onCreate={onCreate} onDone={() => setAdding(false)} />
      ) : (
        <button
          type="button"
          className="border border-border px-2.5 py-0.5 text-body hover:text-ink"
          style={{ borderRadius: 'var(--radius-control)' }}
          onClick={() => setAdding(true)}
        >
          + New category
        </button>
      )}
    </div>
  )
}
