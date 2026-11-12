// Tests for the Today masthead's quiet notice when a brief was made with part of the judging missing.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { BriefDoc } from '../api/types'
import { Masthead } from './Masthead'

function brief(over: Partial<BriefDoc> = {}): BriefDoc {
  return {
    day: '2026-11-12', generated_at: '2026-11-12T06:30:00Z', opening: 'A calm day in your fields.', quiet: false,
    read_minutes: 4, collected: 120, filtered_out: 100, sections: [], ...over,
  }
}

const show = (value: BriefDoc) => render(<Masthead brief={value} days={[value.day]} latestDay={value.day} onAsk={() => undefined} />)

describe('Masthead notice', () => {
  it('shows the notice as one quiet line under the opening when the brief is degraded', () => {
    show(brief({ degraded: true, unjudged: 40, notice: '40 items could not be judged yet; they will appear tomorrow.' }))
    const notice = screen.getByText('40 items could not be judged yet; they will appear tomorrow.')
    expect(notice).toHaveClass('r-masthead__notice')
    expect(notice).not.toHaveAttribute('role', 'alert')
    const opening = screen.getByText('A calm day in your fields.')
    expect(opening.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows no notice for a complete brief, even when one is sent', () => {
    show(brief({ degraded: false, notice: 'Should not show.' }))
    expect(screen.queryByText('Should not show.')).toBeNull()
  })
})
