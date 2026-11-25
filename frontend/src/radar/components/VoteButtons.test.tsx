// Tests for the thumbs: the pressed thumb follows the vote, a click records the reader's vote through
// the shared item state, and a click on the pressed thumb takes the vote back.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { resetItemState } from '../state/itemState'
import { VoteButtons } from './VoteButtons'

/** The vote bodies the service received, in order. */
let sent: unknown[] = []

beforeEach(() => {
  sent = []
  setFetchForTesting(async (input, init) => {
    if (/\/items\/\d+\/vote$/.test(input)) sent.push(JSON.parse(String(init?.body ?? '{}')).vote)
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
})

afterEach(() => {
  cleanup()
  resetItemState()
  setFetchForTesting(null)
})

const up = () => screen.getByRole('button', { name: 'More like this' })
const down = () => screen.getByRole('button', { name: 'Less like this' })

describe('VoteButtons', () => {
  it('presses the thumb that matches the vote', () => {
    const { rerender } = render(<VoteButtons itemId={7} vote="less" />)
    expect(down()).toHaveAttribute('aria-pressed', 'true')
    expect(up()).toHaveAttribute('aria-pressed', 'false')
    rerender(<VoteButtons itemId={7} vote={null} />)
    expect(down()).toHaveAttribute('aria-pressed', 'false')
    expect(up()).toHaveAttribute('aria-pressed', 'false')
  })

  it('sends "more" on a click on thumbs up and lights it at once', async () => {
    render(<VoteButtons itemId={7} vote={null} />)
    fireEvent.click(up())
    expect(up()).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(sent).toEqual(['more']))
  })

  it('clears the vote on a click on the pressed thumb', async () => {
    render(<VoteButtons itemId={8} vote="more" />)
    fireEvent.click(up())
    expect(up()).toHaveAttribute('aria-pressed', 'false')
    await waitFor(() => expect(sent).toEqual([null]))
  })

  it('shows the pair only on a pointed-at or focused row unless it is always shown or a vote is set', () => {
    const { container, rerender } = render(<VoteButtons itemId={9} vote={null} />)
    const pair = container.firstElementChild
    expect(pair).toHaveClass('r-votes')
    expect(pair).not.toHaveClass('r-votes--always')
    expect(pair).not.toHaveClass('is-voted')
    rerender(<VoteButtons itemId={9} vote="less" />)
    expect(pair).toHaveClass('is-voted')
    rerender(<VoteButtons itemId={9} vote={null} always />)
    expect(pair).toHaveClass('r-votes--always')
  })

  it('opens the tooltips downwards when asked, for a bar at the top of the window', () => {
    render(<VoteButtons itemId={10} vote={null} always tipBelow />)
    expect(up().closest('.r-tip')).toHaveClass('r-tip--bottom')
    expect(down().closest('.r-tip')).toHaveClass('r-tip--bottom')
  })
})
