// Test: the Clear button resets the facet dropdowns AND the relevance filter.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { EMPTY_FILTER } from '../lib/filters'
import { FilterBar } from './FilterBar'

const facets = { source: ['A'], category: ['X'], group: [], tag: ['t'] }

describe('FilterBar', () => {
  it('Clear resets the relevance filter back to all', () => {
    const onRelevanceFilter = vi.fn()
    const onChange = vi.fn()
    render(
      <FilterBar
        facets={facets}
        filter={EMPTY_FILTER}
        onChange={onChange}
        relevanceFilter="high"
        onRelevanceFilter={onRelevanceFilter}
        sortBy="collected"
        onSortBy={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(onRelevanceFilter).toHaveBeenCalledWith('all')
    expect(onChange).toHaveBeenCalled()
  })
})
