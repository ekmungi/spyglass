// Tests for the interactive brief narrative: grip selection, the collapsible related
// sub-line (chevron toggle), and card-link routing.
// The selection bar and the drawer's Claude action were
// removed — selection is now surfaced solely via BriefReader's unified control.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { parseBriefBullets } from '../lib/briefBullets'
import { BriefNarrative } from './BriefNarrative'

// Two sections: the first bullet cites two cards inline AND carries a Related
// sub-line (so the collapsible related toggle has something to reveal).
const NARRATIVE = [
  'Overview paragraph about the day.',
  '',
  '## Agentic Systems',
  '',
  '- Alpha ships a new agent citing [Alpha](card:1) and [Beta](card:2).',
  '  - Related: [Gamma](card:3)',
  '- Second theme note with no cards.',
  '',
  '## Robotics',
  '',
  '- A robotics bullet linking [Delta](card:4).',
].join('\n')

/** Build the parsed fixture once per test via the real parser, so the fixture
 * stays honest to the actual grammar instead of a hand-rolled shape. */
function fixture() {
  return parseBriefBullets(NARRATIVE)
}

/** Render BriefNarrative with stubbed callbacks; returns the spies for assertions. */
function renderNarrative(overrides: Partial<Parameters<typeof BriefNarrative>[0]> = {}) {
  const onToggleBullet = vi.fn()
  const onCardLink = vi.fn()
  render(
    <BriefNarrative
      parsed={fixture()}
      selected={new Set()}
      onToggleBullet={onToggleBullet}
      onCardLink={onCardLink}
      {...overrides}
    />,
  )
  return { onToggleBullet, onCardLink }
}

describe('BriefNarrative', () => {
  it('renders a grip per bullet plus the section headings and bullet bodies', () => {
    renderNarrative()
    // 3 bullets total across both sections.
    expect(screen.getAllByRole('button', { name: /select this bullet/i })).toHaveLength(3)
    expect(screen.getByText('Agentic Systems')).toBeInTheDocument()
    expect(screen.getByText('Robotics')).toBeInTheDocument()
    expect(screen.getByText(/second theme note with no cards/i)).toBeInTheDocument()
    expect(screen.getByText(/a robotics bullet linking/i)).toBeInTheDocument()
    expect(screen.getByText('Overview paragraph about the day.')).toBeInTheDocument()
  })

  it('renders no selection bar (removed in favor of the unified control)', () => {
    renderNarrative()
    expect(screen.queryByTestId('brief-selection-bar')).not.toBeInTheDocument()
  })

  it('hides the related sub-line until its chevron toggles it, then reveals clickable links', () => {
    const { onCardLink } = renderNarrative()
    // Collapsed by default: the related card (Gamma) is not rendered.
    expect(screen.queryByText('Gamma')).not.toBeInTheDocument()
    // The chevron toggle exists only for the bullet that has related items.
    fireEvent.click(screen.getByLabelText('Show related items'))
    // Revealed: the related link renders and routes through onCardLink.
    fireEvent.click(screen.getByText('Gamma'))
    expect(onCardLink).toHaveBeenCalledWith(3)
    // Toggling again hides it.
    fireEvent.click(screen.getByLabelText('Hide related items'))
    expect(screen.queryByText('Gamma')).not.toBeInTheDocument()
  })

  it('toggles a bullet grip (selection state lives in the parent)', () => {
    const onToggleBullet = vi.fn()
    render(
      <BriefNarrative
        parsed={fixture()}
        selected={new Set()}
        onToggleBullet={onToggleBullet}
      />,
    )

    const grips = screen.getAllByRole('button', { name: /select this bullet/i })
    fireEvent.click(grips[0])
    expect(onToggleBullet).toHaveBeenCalledWith('0:0')
  })

  it('the grip button is the full hit zone wrapping a slim decorative rule', () => {
    renderNarrative()
    const grips = screen.getAllByRole('button', { name: /select this bullet/i })
    // The button itself is the enlarged click target; the visible mark is a
    // child span so CSS can style hover/selected on the rule, not the whole zone.
    expect(grips[0].querySelector('.brief-bullet-grip-bar')).not.toBeNull()
  })

  it('marks only the selected bullet grip with is-selected (coral bar)', () => {
    // The is-selected class must land on the grip button so the decorative bar
    // can pick up the accent color.
    renderNarrative({ selected: new Set(['0:0']) })
    const grips = screen.getAllByRole('button', { name: /select this bullet/i })
    expect(grips[0]).toHaveClass('is-selected')
    expect(grips[1]).not.toHaveClass('is-selected')
  })

  it('card links inside a bullet body still route through onCardLink', () => {
    const { onCardLink } = renderNarrative()
    fireEvent.click(screen.getByText('Alpha'))
    expect(onCardLink).toHaveBeenCalledWith(1)
  })
})
