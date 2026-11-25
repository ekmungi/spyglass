// Tests for one story row on Today: the two labelled parts of a story with "what it says", the one
// unlabelled text of an older story, both parts in an expanded "Worth knowing" row, the thumbs beside
// Save, and the ring on an unpicked story.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import type { BriefSectionKey } from '../api/types'
import { resetItemState } from '../state/itemState'
import { StoryRow } from './StoryRow'
import { makeStory } from './testStories'

const RING = 'Not picked for today. Thumbs up tells Spyglass that it should have been.'
const WHAT = 'Aster AI released Aster 4, which reads a million tokens in one request.'
const WHY = 'Long documents now fit in one pass.'

/** The votes the service received, as "<item id> <vote>". */
let votes: string[] = []

beforeEach(() => {
  votes = []
  window.history.replaceState(null, '', '/#/today')
  setFetchForTesting(async (url, init) => {
    const match = /\/items\/(\d+)\/vote$/.exec(url)
    if (match) votes.push(`${match[1]} ${JSON.parse(String(init?.body ?? '{}')).vote}`)
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
})

afterEach(() => {
  cleanup()
  resetItemState()
  setFetchForTesting(null)
})

/** Render one row of `section` inside a list, as the brief does. */
function row(section: BriefSectionKey, over: Parameters<typeof makeStory>[1] = {}, unpicked = false) {
  return render(
    <ul>
      <StoryRow story={makeStory(7, over)} section={section} index={0} selected={false} unpicked={unpicked} />
    </ul>,
  )
}

describe('StoryRow', () => {
  it('shows "What it says" and "Why it matters" for a story with both texts', () => {
    row('top', { what: WHAT, why: WHY })
    const what = screen.getByText('What it says')
    const why = screen.getByText('Why it matters')
    expect(what.closest('p')?.textContent).toBe(`What it says${WHAT}`)
    expect(why.closest('p')?.textContent).toBe(`Why it matters${WHY}`)
  })

  it('shows the one older text without a label for a story without "what it says"', () => {
    row('papers', { why: WHY })
    expect(document.querySelectorAll('.r-story__why')).toHaveLength(1)
    expect(screen.getByText(WHY)).toBeInTheDocument()
    expect(screen.queryByText('What it says')).toBeNull()
    expect(screen.queryByText('Why it matters')).toBeNull()
  })

  it('shows both parts when a "Worth knowing" row is expanded', () => {
    row('notable', { what: WHAT, why: WHY })
    expect(screen.queryByText(WHAT)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Why it matters' }))
    expect(screen.getByText('What it says').closest('p')?.textContent).toBe(`What it says${WHAT}`)
    expect(screen.getByText('Why it matters').closest('p')?.textContent).toBe(`Why it matters${WHY}`)
    expect(screen.getByRole('button', { name: 'Hide why it matters' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('lets a "Worth knowing" row with only "what it says" expand', () => {
    row('notable', { what: WHAT, why: null })
    fireEvent.click(screen.getByRole('button', { name: 'Why it matters' }))
    expect(screen.getByText('What it says').closest('p')?.textContent).toBe(`What it says${WHAT}`)
  })

  it.each<BriefSectionKey>(['top', 'notable', 'skim'])('puts the thumbs beside Save on a %s row', (section) => {
    row(section)
    const item = screen.getByRole('listitem')
    expect(within(item).getByRole('button', { name: 'More like this' })).toBeInTheDocument()
    expect(within(item).getByRole('button', { name: 'Less like this' })).toBeInTheDocument()
    expect(within(item).getByRole('button', { name: 'Save for later' })).toBeInTheDocument()
  })

  it('sends the vote on a click on a thumb, without opening the story', async () => {
    row('top')
    fireEvent.click(screen.getByRole('button', { name: 'More like this' }))
    await waitFor(() => expect(votes).toEqual(['7 more']))
    expect(screen.getByRole('button', { name: 'More like this' })).toHaveAttribute('aria-pressed', 'true')
    expect(window.location.hash).toBe('#/today')
  })

  it.each<BriefSectionKey>(['top', 'notable', 'skim'])('draws the ring on an unpicked %s story only', (section) => {
    const picked = row(section)
    expect(screen.queryByRole('img', { name: RING })).toBeNull()
    picked.unmount()
    row(section, {}, true)
    const ring = screen.getByRole('img', { name: RING })
    expect(ring).toHaveAttribute('title', RING)
    expect(ring.closest('.r-story__headline')).not.toBeNull()
  })
})
