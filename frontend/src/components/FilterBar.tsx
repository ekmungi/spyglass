// Filter panel: facet dropdowns (source, category, tag), the relevance hide-filter,
// and the list sort toggle.
import { RELEVANCE_FILTERS, type RelevanceFilter } from '../lib/relevance'
import type { Facets, FilterState } from '../lib/filters'

/** List orderings: collected = served order (newest arrivals), published = article date. */
export type SortBy = 'collected' | 'published'

interface Props {
  facets: Facets
  filter: FilterState
  onChange: (filter: FilterState) => void
  relevanceFilter: RelevanceFilter
  onRelevanceFilter: (value: RelevanceFilter) => void
  sortBy: SortBy
  onSortBy: (value: SortBy) => void
}

/** One labelled dropdown; rendered only when the facet has values. */
function FacetSelect({
  label,
  field,
  values,
  filter,
  onChange,
}: {
  label: string
  field: keyof FilterState
  values: string[]
  filter: FilterState
  onChange: (filter: FilterState) => void
}) {
  if (values.length === 0) {
    return null
  }
  return (
    <label className="flex items-center gap-1 text-muted">
      {label}
      <select
        aria-label={label}
        className="rounded border border-border bg-card px-2 py-1 text-body"
        value={filter[field]}
        onChange={(event) => onChange({ ...filter, [field]: event.target.value })}
      >
        <option value="all">All</option>
        {values.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Filter dropdowns shown when the Filter toggle is open. */
export function FilterBar({ facets, filter, onChange, relevanceFilter, onRelevanceFilter, sortBy, onSortBy }: Props) {
  return (
    <div
      className="flex flex-wrap items-center gap-3 border border-border bg-card p-3"
      style={{ fontSize: 'var(--font-size-actions)', borderRadius: 'var(--radius-card)' }}
    >
      <FacetSelect label="Source" field="source" values={facets.source} filter={filter} onChange={onChange} />
      <FacetSelect label="Category" field="category" values={facets.category} filter={filter} onChange={onChange} />
      <FacetSelect label="Tag" field="tag" values={facets.tag} filter={filter} onChange={onChange} />
      <label className="flex items-center gap-1 text-muted">
        Relevance
        <select
          aria-label="Relevance filter"
          className="rounded border border-border bg-card px-2 py-1 text-body"
          value={relevanceFilter}
          onChange={(event) => onRelevanceFilter(event.target.value as RelevanceFilter)}
        >
          {RELEVANCE_FILTERS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1 text-muted">
        Sort
        <select
          aria-label="Sort"
          className="rounded border border-border bg-card px-2 py-1 text-body"
          value={sortBy}
          onChange={(event) => onSortBy(event.target.value as SortBy)}
        >
          <option value="collected">Newest arrivals</option>
          <option value="published">Recently published</option>
        </select>
      </label>
      <button
        type="button"
        className="text-accent"
        onClick={() => {
          // Clear resets the facet dropdowns AND the relevance filter, so a level filter that
          // is currently hiding rows returns to showing everything.
          onChange({ source: 'all', category: 'all', group: filter.group, tag: 'all' })
          onRelevanceFilter('all')
        }}
      >
        Clear
      </button>
    </div>
  )
}
