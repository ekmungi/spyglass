// Tests for the shared thumbs control: toggle semantics + the tap-to-select pop.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ThumbsControl } from './ThumbsControl'

const noop = () => {}

function renderControl(overrides: Partial<Parameters<typeof ThumbsControl>[0]> = {}) {
  return render(
    <ThumbsControl feedback={null} onFeedback={noop} btnClass="btn" iconSize={14} {...overrides} />,
  )
}

describe('ThumbsControl', () => {
  it('calls onFeedback("up") and pops the thumb when selected from unrated', () => {
    const onFeedback = vi.fn()
    renderControl({ feedback: null, onFeedback })
    const up = screen.getByRole('button', { name: 'Thumbs up' })
    fireEvent.click(up)
    expect(onFeedback).toHaveBeenCalledWith('up')
    expect(up.className).toContain('thumb-pop')
  })

  it('does NOT pop when clearing an already-active thumb', () => {
    const onFeedback = vi.fn()
    renderControl({ feedback: 'up', onFeedback })
    const up = screen.getByRole('button', { name: 'Thumbs up' })
    fireEvent.click(up)
    expect(onFeedback).toHaveBeenCalledWith(null)
    expect(up.className).not.toContain('thumb-pop')
  })

  // Note: the pop class is removed onAnimationEnd. jsdom does not reliably deliver
  // animationend to React 19's delegated handler, so that cleanup is verified in-browser
  // rather than here; the tap-to-select trigger logic above is the part worth unit-testing.

  it('marks the active thumb as pressed and does not pop on mount', () => {
    renderControl({ feedback: 'down' })
    const down = screen.getByRole('button', { name: 'Thumbs down' })
    expect(down).toHaveAttribute('aria-pressed', 'true')
    // Rendering a rated card (e.g. scrolled back into view) must not animate.
    expect(down.className).not.toContain('thumb-pop')
  })

  // A rated thumb must be unmistakable at rest, not just a faint outline --
  // the active icon fills solid in a semantic colour (up = ok green, down = out red).
  it('fills the up icon and colors it text-ok when feedback is "up"', () => {
    renderControl({ feedback: 'up' })
    const up = screen.getByRole('button', { name: 'Thumbs up' })
    expect(up.className).toContain('text-ok')
    expect(up.querySelector('svg')).toHaveAttribute('fill', 'currentColor')
  })

  it('fills the down icon and colors it text-out when feedback is "down"', () => {
    renderControl({ feedback: 'down' })
    const down = screen.getByRole('button', { name: 'Thumbs down' })
    expect(down.className).toContain('text-out')
    expect(down.querySelector('svg')).toHaveAttribute('fill', 'currentColor')
  })

  it('leaves both thumbs unfilled and uncolored when feedback is null', () => {
    renderControl({ feedback: null })
    const up = screen.getByRole('button', { name: 'Thumbs up' })
    const down = screen.getByRole('button', { name: 'Thumbs down' })
    expect(up.className).not.toContain('text-ok')
    expect(down.className).not.toContain('text-out')
    expect(up.querySelector('svg')).toHaveAttribute('fill', 'none')
    expect(down.querySelector('svg')).toHaveAttribute('fill', 'none')
  })
})
