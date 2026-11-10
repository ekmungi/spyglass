// Tests for the bulk selection bar: actions, archive, relevance, category.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SelectionBar } from './SelectionBar'

const categories = [
  { name: 'Agentic AI', count: 3 },
  { name: 'Empty bucket', count: 0 },
]

const noop = () => {}

function renderBar(overrides: Partial<Parameters<typeof SelectionBar>[0]> = {}) {
  return render(
    <SelectionBar
      count={2}
      categories={categories}
      onAction={noop}
      onArchive={noop}
      onBulkRelevance={noop}
      onBulkCategory={noop}
      onClear={noop}
      {...overrides}
    />,
  )
}

describe('SelectionBar', () => {
  it('is hidden when nothing is selected', () => {
    renderBar({ count: 0 })
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument()
  })

  it('shows the count and the session actions', () => {
    const onAction = vi.fn()
    renderBar({ onAction })
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Synthesize' }))
    expect(onAction).toHaveBeenCalledWith('synthesize')
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
    expect(onAction).toHaveBeenCalledWith('compare')
    fireEvent.click(screen.getByRole('button', { name: 'Deep dive' }))
    expect(onAction).toHaveBeenCalledWith('deepdive')
    fireEvent.click(screen.getByRole('button', { name: 'Open in Claude' }))
    expect(onAction).toHaveBeenCalledWith('open')
  })

  it('archives the selection', () => {
    const onArchive = vi.fn()
    renderBar({ onArchive })
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
    expect(onArchive).toHaveBeenCalled()
  })

  it('sets bulk relevance from the mini segmented control', () => {
    const onBulkRelevance = vi.fn()
    renderBar({ onBulkRelevance })
    fireEvent.click(screen.getByRole('button', { name: 'H' }))
    expect(onBulkRelevance).toHaveBeenCalledWith('high')
  })

  it('sets bulk category from the dropdown, including empty categories', () => {
    const onBulkCategory = vi.fn()
    renderBar({ onBulkCategory })
    const select = screen.getByRole('combobox', { name: 'Set category for selected' })
    expect(screen.getByRole('option', { name: 'Empty bucket' })).toBeInTheDocument()
    fireEvent.change(select, { target: { value: 'Agentic AI' } })
    expect(onBulkCategory).toHaveBeenCalledWith('Agentic AI')
  })

  it('clears the selection', () => {
    const onClear = vi.fn()
    renderBar({ onClear })
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(onClear).toHaveBeenCalled()
  })
})
