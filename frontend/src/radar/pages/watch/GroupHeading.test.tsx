// A Watch group's heading: its name, the count that links to the Feed's list of exactly those
// items, and the group menu, which can also move the group up or down the page.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GroupHeading, type GroupHeadingProps } from './GroupHeading'
import type { LayoutGroup } from './organize'

const group = (changes: Partial<LayoutGroup> = {}): LayoutGroup => ({ name: 'AI labs', entities: [], weekCount: 3, ...changes })

function renderHeading(changes: Partial<LayoutGroup> = {}, props: Partial<GroupHeadingProps> = {}) {
  const onAction = vi.fn()
  render(<GroupHeading id="g" group={group(changes)} paused={false} first={false} last={false} busy={false} onAction={onAction} {...props} />)
  return onAction
}

/** The labels of the group menu, opened. */
function menuLabels(): string[] {
  fireEvent.click(screen.getByRole('button', { name: 'Actions for the group AI labs' }))
  return screen.getAllByRole('menuitem').map((item) => item.textContent ?? '')
}

describe('GroupHeading week count', () => {
  it('links the count to the Feed filtered to the group', () => {
    renderHeading()
    const link = screen.getByRole('link', { name: '3 items this week' })
    expect(link).toHaveAttribute('href', '#/feed?watch_group=AI+labs')
  })

  it('writes a name with symbols so it reads back whole', () => {
    renderHeading({ name: 'R&D / labs' })
    const href = screen.getByRole('link', { name: '3 items this week' }).getAttribute('href') ?? ''
    expect(new URLSearchParams(href.split('?')[1]).get('watch_group')).toBe('R&D / labs')
  })

  it('says "1 item this week" for one', () => {
    renderHeading({ weekCount: 1 })
    expect(screen.getByRole('link', { name: '1 item this week' })).toBeInTheDocument()
  })

  it('is plain text when nothing new came in, because the list would be empty', () => {
    renderHeading({ weekCount: 0 })
    expect(screen.getByText('Nothing new this week')).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('shows nothing when the count is unknown', () => {
    renderHeading({ weekCount: null })
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.queryByText(/this week/)).toBeNull()
  })

  it('keeps the group name as a heading and the group menu', () => {
    renderHeading()
    expect(screen.getByRole('heading', { level: 3, name: 'AI labs' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Actions for the group AI labs' })).toBeInTheDocument()
  })
})

describe('GroupHeading menu', () => {
  it('offers pause, Move up and Move down, and the renaming and removing actions', () => {
    renderHeading()
    expect(menuLabels()).toEqual(['Pause this group', 'Move up', 'Move down', 'Rename group…', 'Move all to another group…', 'Remove this group…'])
  })

  it('sends up and down', () => {
    const onAction = renderHeading()
    menuLabels()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Move down' }))
    expect(onAction).toHaveBeenCalledWith('down')
    menuLabels()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Move up' }))
    expect(onAction).toHaveBeenCalledWith('up')
  })

  it('cannot move the first group up or the last group down', () => {
    const onAction = renderHeading({}, { first: true, last: true })
    menuLabels()
    expect(screen.getByRole('menuitem', { name: 'Move up' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('menuitem', { name: 'Move down' })).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(screen.getByRole('menuitem', { name: 'Move up' }))
    expect(onAction).not.toHaveBeenCalled()
  })

  it('offers to watch the group again when none of its names is watched now', () => {
    const onAction = renderHeading({}, { paused: true })
    expect(menuLabels()[0]).toBe('Watch this group again')
    fireEvent.click(screen.getByRole('menuitem', { name: 'Watch this group again' }))
    expect(onAction).toHaveBeenCalledWith('resume')
  })
})
