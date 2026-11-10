// Tests for the category chip bar: counts, selection, inline create + rename.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CategoryChips } from './CategoryChips'

const categories = [
  { name: 'Agentic AI', count: 3 },
  { name: 'Healthcare AI', count: 1 },
  { name: 'Empty bucket', count: 0 },
]

const noop = () => {}

function renderChips(overrides: Partial<Parameters<typeof CategoryChips>[0]> = {}) {
  return render(
    <CategoryChips
      categories={categories}
      active="All"
      onSelect={noop}
      onCreate={noop}
      onRename={noop}
      {...overrides}
    />,
  )
}

describe('CategoryChips', () => {
  it('shows All plus only the categories that have items, with counts', () => {
    renderChips()
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Agentic AI (3)' })).toBeInTheDocument()
    // Empty categories live on in dropdowns only, not as chips.
    expect(screen.queryByText(/Empty bucket/)).not.toBeInTheDocument()
  })

  it('reports the clicked category', () => {
    const onSelect = vi.fn()
    renderChips({ onSelect })
    fireEvent.click(screen.getByRole('button', { name: 'Healthcare AI (1)' }))
    expect(onSelect).toHaveBeenCalledWith('Healthcare AI')
  })

  it('creates a new empty category from the inline input', () => {
    const onCreate = vi.fn()
    renderChips({ onCreate })
    fireEvent.click(screen.getByRole('button', { name: '+ New category' }))
    const input = screen.getByRole('textbox', { name: 'New category name' })
    fireEvent.change(input, { target: { value: 'Robotics' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onCreate).toHaveBeenCalledWith('Robotics')
  })

  it('cancels the inline input on Escape without creating', () => {
    const onCreate = vi.fn()
    renderChips({ onCreate })
    fireEvent.click(screen.getByRole('button', { name: '+ New category' }))
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'New category name' }), {
      key: 'Escape',
    })
    expect(onCreate).not.toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('renames the ACTIVE category from its pencil, prefilled inline', () => {
    const onRename = vi.fn()
    renderChips({ active: 'Agentic AI', onRename })
    fireEvent.click(screen.getByRole('button', { name: 'Rename Agentic AI' }))
    const input = screen.getByRole('textbox', {
      name: 'Rename category Agentic AI',
    }) as HTMLInputElement
    expect(input.value).toBe('Agentic AI')
    fireEvent.change(input, { target: { value: 'Agent Systems' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onRename).toHaveBeenCalledWith('Agentic AI', 'Agent Systems')
  })

  it('offers no rename pencil on inactive chips', () => {
    renderChips({ active: 'All' })
    expect(screen.queryByRole('button', { name: /^Rename/ })).not.toBeInTheDocument()
  })

})
