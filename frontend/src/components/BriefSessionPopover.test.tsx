// Tests for the transient Open-in-Claude scope popover: the
// one-session launch (no per-bullet mode), removable related chips, the
// seeded-prompt preview, and Esc/backdrop/Launch dismissal.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BriefSessionPopover, type SelectedBullet } from './BriefSessionPopover'

// Two selected bullets, each with distinct loaded cards + related cards, so the
// combine union and per-bullet calls are each independently verifiable.
const BULLETS: SelectedBullet[] = [
  {
    key: '0:0',
    cards: [{ id: 1, title: 'Alpha' }],
    related: [
      { id: 3, title: 'Gamma' },
      { id: 4, title: 'Delta' },
    ],
  },
  {
    key: '1:0',
    cards: [{ id: 2, title: 'Beta' }],
    related: [{ id: 5, title: 'Epsilon' }],
  },
]

/** Render the popover with stubbed callbacks; returns the spies for assertions. */
function renderPopover(bullets: SelectedBullet[] = BULLETS) {
  const onOpenClaude = vi.fn()
  const onClose = vi.fn()
  render(<BriefSessionPopover bullets={bullets} onOpenClaude={onOpenClaude} onClose={onClose} />)
  return { onOpenClaude, onClose }
}

describe('BriefSessionPopover', () => {
  it('Combine (default): Launch calls onOpenClaude once with the deduped union of kept ids', () => {
    const { onOpenClaude } = renderPopover()
    fireEvent.click(screen.getByRole('button', { name: /^launch$/i }))
    expect(onOpenClaude).toHaveBeenCalledTimes(1)
    const [cardIds, prompt] = onOpenClaude.mock.calls[0]
    expect(new Set(cardIds)).toEqual(new Set([1, 3, 4, 2, 5]))
    // Prompt names the selected topics (card titles).
    expect(prompt).toContain('Alpha')
    expect(prompt).toContain('Beta')
  })

  it('opens one session for all selected bullets: there is no one-per-bullet mode', () => {
    renderPopover()
    expect(screen.queryByRole('button', { name: /one per bullet/i })).not.toBeInTheDocument()
  })

  it('removing a related chip drops its id from the combined launch set', () => {
    const { onOpenClaude } = renderPopover()
    fireEvent.click(screen.getByRole('button', { name: /remove gamma/i }))
    fireEvent.click(screen.getByRole('button', { name: /^launch$/i }))
    const [cardIds] = onOpenClaude.mock.calls[0]
    expect(cardIds).not.toContain(3)
    expect(new Set(cardIds)).toEqual(new Set([1, 4, 2, 5]))
  })

  it('loaded cards are always present in the launched set (not removable)', () => {
    // Loaded-card chips carry no remove button at all.
    renderPopover()
    expect(screen.queryByRole('button', { name: /remove alpha/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove beta/i })).not.toBeInTheDocument()
  })

  it('Esc calls onClose', () => {
    const { onClose } = renderPopover()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('backdrop click calls onClose', () => {
    const { onClose } = renderPopover()
    fireEvent.click(screen.getByTestId('brief-session-popover-backdrop'))
    expect(onClose).toHaveBeenCalled()
  })

  it('Launch calls onClose after emitting', () => {
    const { onClose, onOpenClaude } = renderPopover()
    fireEvent.click(screen.getByRole('button', { name: /^launch$/i }))
    expect(onOpenClaude).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('collapses more than 2 related chips behind a "+N more related" reveal', () => {
    const many: SelectedBullet[] = [
      {
        key: '0:0',
        cards: [{ id: 1, title: 'Alpha' }],
        related: [
          { id: 3, title: 'Gamma' },
          { id: 4, title: 'Delta' },
          { id: 5, title: 'Epsilon' },
          { id: 6, title: 'Zeta' },
        ],
      },
    ]
    renderPopover(many)
    // Only the first 2 related chips render initially.
    expect(screen.getByRole('button', { name: /remove gamma/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /remove delta/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove epsilon/i })).not.toBeInTheDocument()
    const reveal = screen.getByRole('button', { name: /\+2 more related/i })
    fireEvent.click(reveal)
    // Client-side reveal: the rest now render without any new onOpenClaude/fetch call.
    expect(screen.getByRole('button', { name: /remove epsilon/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /remove zeta/i })).toBeInTheDocument()
  })
})
