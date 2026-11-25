// Tests for the Today masthead and the line about unjudged items: that line now closes the page
// (TodayPage puts it at the end of the article), so the masthead never shows it.
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

describe('Masthead', () => {
  it('shows the opening and leaves the line about unjudged items to the end of the page', () => {
    const notice = "40 collected items are still waiting to be judged, so a story may be missing from today's selection."
    const { container } = show(brief({ degraded: true, unjudged: 40, notice }))
    expect(screen.getByText('A calm day in your fields.')).toHaveClass('r-masthead__opening')
    expect(screen.queryByText(notice)).toBeNull()
    expect(container.querySelector('.r-masthead__notice')).toBeNull()
  })
})
