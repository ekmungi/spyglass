// The count on a Watch group's heading is a link to the Feed's list of exactly those items; the
// rest of the heading is unchanged.
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GroupHeading } from './GroupHeading'
import type { OrganizedGroup } from './organize'

const group = (changes: Partial<OrganizedGroup> = {}): OrganizedGroup => ({ name: 'AI labs', entities: [], paused: false, weekCount: 3, ...changes })

function renderHeading(changes: Partial<OrganizedGroup> = {}) {
  return render(<GroupHeading id="g" group={group(changes)} busy={false} onAction={vi.fn()} />)
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

  it('shows nothing when the count is unknown, and "Paused" with Resume for a paused group', () => {
    const view = renderHeading({ weekCount: null })
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.queryByText(/this week/)).toBeNull()
    view.unmount()
    renderHeading({ paused: true })
    expect(screen.getByText('Paused')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resume AI labs' })).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('keeps the group name and the group menu', () => {
    renderHeading()
    expect(screen.getByRole('heading', { name: 'AI labs' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Actions for the group AI labs' })).toBeInTheDocument()
  })
})
