// Tests for the compact reader toolbar: icons, dot/chip popovers, net-change.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { makeCard } from '../../test/fixtures'
import { ReaderToolbar } from './ReaderToolbar'

const categories = [
  { name: 'Agentic AI', count: 3 },
  { name: 'Healthcare AI', count: 1 },
]

const card = makeCard({
  id: 5,
  relevance: 'medium',
  relevance_ai: 'medium',
  category: 'Agentic AI',
  category_ai: 'Agentic AI',
})

const noop = () => {}

function renderBar(overrides: Partial<Parameters<typeof ReaderToolbar>[0]> = {}) {
  return render(
    <ReaderToolbar
      card={card}
      categories={categories}
      onArchive={noop}
      onSetRelevance={noop}
      onSetCategory={noop}
      onCreateCategory={noop}
      onSend={noop}
      {...overrides}
    />,
  )
}

describe('ReaderToolbar', () => {
  it('shows the icon actions and Send to Claude', () => {
    const onArchive = vi.fn()
    const onSend = vi.fn()
    renderBar({ onArchive, onSend })
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
    expect(onArchive).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /send to claude/i }))
    expect(onSend).toHaveBeenCalled()
  })

  it('renders thumbs and reflects the active state from the card', () => {
    renderBar({ card: makeCard({ id: 7, feedback: 'up' }), onFeedback: noop })
    expect(screen.getByRole('button', { name: 'Thumbs up' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Thumbs down' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('calls onFeedback("down") when thumbs down is tapped while unrated', () => {
    const onFeedback = vi.fn()
    renderBar({ card: makeCard({ id: 7, feedback: null }), onFeedback })
    fireEvent.click(screen.getByRole('button', { name: 'Thumbs down' }))
    expect(onFeedback).toHaveBeenCalledWith('down')
  })

  it('hides thumbs when no onFeedback handler is provided', () => {
    renderBar()
    expect(screen.queryByRole('button', { name: 'Thumbs up' })).not.toBeInTheDocument()
  })

  it('leaves the note to the job bar: no Read briefing here', () => {
    renderBar({
      card: makeCard({ id: 6, state: 'finished', briefing_path: 'C:/vault/briefing.md' }),
    })
    expect(screen.queryByRole('button', { name: 'Read briefing' })).not.toBeInTheDocument()
  })

  it('opens the relevance popover from the dot and marks the AI value', () => {
    const onSetRelevance = vi.fn()
    renderBar({ onSetRelevance })
    fireEvent.click(screen.getByRole('button', { name: /relevance: medium/i }))
    expect(screen.getByRole('button', { name: 'Med (AI)' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'High' }))
    expect(onSetRelevance).toHaveBeenCalledWith('high')
  })

  it('rings the dot and titles it "you set" only on a net change', () => {
    renderBar({
      card: makeCard({ id: 7, relevance: 'high', relevance_ai: 'medium', relevance_override: true }),
    })
    const dot = screen.getByRole('button', { name: /relevance: high \(you set\)/i })
    expect(dot.className).toContain('override')
  })

  it('opens the category menu from the chip and assigns a category', () => {
    const onSetCategory = vi.fn()
    renderBar({ onSetCategory })
    fireEvent.click(screen.getByRole('button', { name: /Agentic AI/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Healthcare AI' }))
    expect(onSetCategory).toHaveBeenCalledWith('Healthcare AI')
  })

  it('creates an empty category from the menu WITHOUT moving the item', () => {
    const onSetCategory = vi.fn()
    const onCreateCategory = vi.fn()
    renderBar({ onSetCategory, onCreateCategory })
    fireEvent.click(screen.getByRole('button', { name: /Agentic AI/ }))
    fireEvent.click(screen.getByRole('button', { name: '+ New category' }))
    const input = screen.getByRole('textbox', { name: 'New category name' })
    fireEvent.change(input, { target: { value: 'Robotics' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onCreateCategory).toHaveBeenCalledWith('Robotics')
    expect(onSetCategory).not.toHaveBeenCalled()
  })

  it('clicking "Clear" in the relevance popover calls onSetRelevance with null', () => {
    const onSetRelevance = vi.fn()
    renderBar({ onSetRelevance })
    fireEvent.click(screen.getByRole('button', { name: /relevance: medium/i }))
    fireEvent.click(screen.getByRole('button', { name: /clear relevance override/i }))
    expect(onSetRelevance).toHaveBeenCalledWith(null)
  })

  it('marks an overridden category chip', () => {
    renderBar({
      card: makeCard({
        id: 8,
        category: 'Healthcare AI',
        category_ai: 'Agentic AI',
        category_override: true,
      }),
    })
    const chip = screen.getByRole('button', { name: /Healthcare AI/ })
    expect(chip.className).toContain('override')
  })
})
