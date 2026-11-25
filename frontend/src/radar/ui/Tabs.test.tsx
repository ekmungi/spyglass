// Tests for the strip of tabs: one selected tab, a click or an arrow key chooses another, and an
// alert mark is read out by its own text.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Tabs, type TabItem } from './Tabs'

const TABS: TabItem[] = [
  { key: 'everything', label: 'Everything' },
  { key: 'missed', label: 'Missed', count: 12 },
  { key: 'saved', label: 'Saved' },
]

describe('Tabs', () => {
  it('is a named tab list with exactly the chosen tab selected', () => {
    render(<Tabs tabs={TABS} value="missed" onChange={() => undefined} label="Views" />)
    const list = screen.getByRole('tablist', { name: 'Views' })
    expect(list).toBeInTheDocument()
    const selected = screen.getAllByRole('tab').filter((tab) => tab.getAttribute('aria-selected') === 'true')
    expect(selected).toHaveLength(1)
    expect(selected[0]).toHaveAccessibleName('Missed 12')
    // Only the selected tab is a tab stop; the arrows move between the others.
    expect(selected[0]).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('tab', { name: 'Saved' })).toHaveAttribute('tabindex', '-1')
  })

  it('keeps the first tab as the tab stop when no tab matches the value', () => {
    render(<Tabs tabs={TABS} value="watch" onChange={() => undefined} label="Views" />)
    expect(screen.getAllByRole('tab').filter((tab) => tab.getAttribute('aria-selected') === 'true')).toHaveLength(0)
    expect(screen.getByRole('tab', { name: 'Everything' })).toHaveAttribute('tabindex', '0')
  })

  it('calls onChange with the key of the clicked tab', () => {
    const onChange = vi.fn()
    render(<Tabs tabs={TABS} value="everything" onChange={onChange} label="Views" />)
    fireEvent.click(screen.getByRole('tab', { name: 'Saved' }))
    expect(onChange).toHaveBeenCalledWith('saved')
  })

  it('moves the selection to the next tab with ArrowRight and back with ArrowLeft', () => {
    const onChange = vi.fn()
    render(<Tabs tabs={TABS} value="everything" onChange={onChange} label="Views" />)
    const first = screen.getByRole('tab', { name: 'Everything' })
    fireEvent.keyDown(first, { key: 'ArrowRight' })
    expect(onChange).toHaveBeenLastCalledWith('missed')
    expect(screen.getByRole('tab', { name: /^Missed/ })).toHaveFocus()
    fireEvent.keyDown(first, { key: 'ArrowLeft' })
    // From the first tab, the left arrow wraps round to the last.
    expect(onChange).toHaveBeenLastCalledWith('saved')
  })

  it('gives an alert mark its text as accessible name', () => {
    const tabs: TabItem[] = [...TABS, { key: 'feeds', label: 'Feeds', alert: 'One feed is failing' }]
    render(<Tabs tabs={tabs} value="everything" onChange={() => undefined} label="Sources" />)
    expect(screen.getByRole('img', { name: 'One feed is failing' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /^Feeds/ })).toContainElement(screen.getByRole('img', { name: 'One feed is failing' }))
  })

  it('puts the title of a tab on its button as hover text, and leaves the others without one', () => {
    const tabs: TabItem[] = [{ key: 'a', label: 'First', title: 'The first one' }, { key: 'b', label: 'Second' }]
    render(<Tabs tabs={tabs} value="a" onChange={() => undefined} label="Views" />)
    expect(screen.getByRole('tab', { name: 'First' })).toHaveAttribute('title', 'The first one')
    expect(screen.getByRole('tab', { name: 'Second' })).not.toHaveAttribute('title')
  })

  it('draws the lighter look of a second strip when quiet', () => {
    const { container } = render(<Tabs tabs={TABS} value="saved" onChange={() => undefined} label="Sections" quiet />)
    expect(container.firstElementChild).toHaveClass('r-tabs', 'r-tabs--quiet')
  })
})
