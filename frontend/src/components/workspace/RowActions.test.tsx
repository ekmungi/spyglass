// Tests for the per-item action cluster: four buttons and two-step delete confirm.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RowActions } from './RowActions'

const noop = () => {}

/** Render with no-op callbacks and an unrated card by default; override per test. */
function renderActions(overrides: Partial<Parameters<typeof RowActions>[0]> = {}) {
  return render(
    <RowActions
      feedback={null}
      onFeedback={noop}
      onClaude={noop}
      onOpenExternal={noop}
      onArchive={noop}
      onDelete={noop}
      {...overrides}
    />,
  )
}

describe('RowActions', () => {
  it('renders four action buttons', () => {
    renderActions()
    expect(screen.getByRole('button', { name: 'Open in Claude' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open in browser' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Archive' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('renders thumbs up and down buttons', () => {
    renderActions()
    expect(screen.getByRole('button', { name: 'Thumbs up' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thumbs down' })).toBeInTheDocument()
  })

  it('calls onFeedback("up") when thumbs up is tapped while unrated', () => {
    const onFeedback = vi.fn()
    renderActions({ feedback: null, onFeedback })
    fireEvent.click(screen.getByRole('button', { name: 'Thumbs up' }))
    expect(onFeedback).toHaveBeenCalledWith('up')
  })

  it('calls onFeedback(null) when tapping the already-active thumb (clear)', () => {
    const onFeedback = vi.fn()
    renderActions({ feedback: 'up', onFeedback })
    fireEvent.click(screen.getByRole('button', { name: 'Thumbs up' }))
    expect(onFeedback).toHaveBeenCalledWith(null)
  })

  it('marks the active thumb as pressed', () => {
    renderActions({ feedback: 'down' })
    expect(screen.getByRole('button', { name: 'Thumbs down' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Thumbs up' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('fires onClaude immediately on click', () => {
    const onClaude = vi.fn()
    renderActions({ onClaude })
    fireEvent.click(screen.getByRole('button', { name: 'Open in Claude' }))
    expect(onClaude).toHaveBeenCalledTimes(1)
  })

  it('fires onOpenExternal immediately on click', () => {
    const onOpenExternal = vi.fn()
    renderActions({ onOpenExternal })
    fireEvent.click(screen.getByRole('button', { name: 'Open in browser' }))
    expect(onOpenExternal).toHaveBeenCalledTimes(1)
  })

  it('fires onArchive immediately on click', () => {
    const onArchive = vi.fn()
    renderActions({ onArchive })
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
    expect(onArchive).toHaveBeenCalledTimes(1)
  })

  it('does NOT fire onDelete on first click — shows the confirm button instead', () => {
    const onDelete = vi.fn()
    renderActions({ onDelete })
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onDelete).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Confirm delete' })).toBeInTheDocument()
  })

  it('fires onDelete on second click (the confirm step)', () => {
    const onDelete = vi.fn()
    renderActions({ onDelete })
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))
    expect(onDelete).toHaveBeenCalledTimes(1)
  })

  it('Cancel button resets the confirming state without firing onDelete', () => {
    const onDelete = vi.fn()
    renderActions({ onDelete })
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel delete' }))
    expect(onDelete).not.toHaveBeenCalled()
    // Back to initial state: trash button visible, no confirm.
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm delete' })).not.toBeInTheDocument()
  })
})
