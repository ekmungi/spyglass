// Tests for the linked-session indicator in the header.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LinkIndicator } from './LinkIndicator'

describe('LinkIndicator', () => {
  it('shows the link state and opens a new linked session', () => {
    const onOpen = vi.fn()
    const now = new Date().toISOString()
    render(
      <LinkIndicator
        status={{ linked: true, linked_at: now, last_seen: now, waiting: false }}
        onOpen={onOpen}
      />,
    )
    expect(screen.getByText(/^Linked to Claude/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open a linked Claude session' }))
    expect(onOpen).toHaveBeenCalled()
  })

  it('says when no session is linked', () => {
    render(<LinkIndicator status={null} onOpen={() => {}} onEnd={() => {}} />)
    expect(screen.getByText('No linked Claude session')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /end the link/i })).not.toBeInTheDocument()
  })

  it('ends the link while a session is linked', () => {
    const onEnd = vi.fn()
    const now = new Date().toISOString()
    render(
      <LinkIndicator
        status={{ linked: true, linked_at: now, last_seen: now, waiting: false }}
        onOpen={() => {}}
        onEnd={onEnd}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /end the link/i }))
    expect(onEnd).toHaveBeenCalled()
  })

  it('says why there is no link any more', () => {
    render(
      <LinkIndicator
        status={{ linked: false, linked_at: null, last_seen: null, waiting: false, ended: 'closed' }}
        onOpen={() => {}}
      />,
    )
    expect(screen.getByText('Link ended when Spyglass closed')).toBeInTheDocument()
  })
})
