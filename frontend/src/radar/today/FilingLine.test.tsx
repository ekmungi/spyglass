// Tests for the filing line under Today's masthead: shown only with something to say, linking to
// the Feed's To file view, and fed by the `filing` field of GET /today.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import type { TodayResponse } from '../api/types'
import { clearResourceCache } from '../hooks/useResource'
import { resetFilingConfigured, setFilingConfigured } from '../state/filingConfigured'
import { buildBrief } from '../mock/brief'
import { buildItems } from '../mock/items'
import { TodayPage } from '../pages/TodayPage'
import { FilingLine } from './FilingLine'

const DAY = '2026-11-12'

beforeEach(() => {
  // These tests are about an install where filing is set up; the one about the other case says so.
  setFilingConfigured(true)
  clearResourceCache()
  window.history.replaceState(null, '', '/#/today')
})

afterEach(() => {
  cleanup()
  resetFilingConfigured()
  setFetchForTesting(null)
})

/** Serve /today with the given filing summary. */
function serve(filing: TodayResponse['filing']) {
  const today: TodayResponse = { brief: buildBrief(buildItems(), DAY), days: [DAY], status: {}, filing }
  setFetchForTesting(async (url) => {
    if (url.endsWith('/today')) return new Response(JSON.stringify(today), { status: 200 })
    if (url.endsWith('/profile')) return new Response(JSON.stringify({ sections: [] }), { status: 200 })
    return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 })
  })
}

describe('FilingLine', () => {
  it('says nothing without a line', () => {
    const { container } = render(<FilingLine text={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('says nothing where filing is not set up', () => {
    setFilingConfigured(false)
    const { container } = render(<FilingLine text="Filed yesterday: 9 items." />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the line and opens the To file view', () => {
    render(<FilingLine text="Filed yesterday: 9 items. 2 questions are open." />)
    expect(screen.getByText(/Filed yesterday: 9 items. 2 questions are open./)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: 'Open To file' }))
    expect(window.location.hash).toBe('#/feed?filing=waiting')
  })
})

describe('Today with a filing line', () => {
  it('shows the line under the masthead when the service sends one', async () => {
    serve({ line: 'Filing has not run since Tuesday: Obsidian was closed.', filed_yesterday: 0, questions: 0, plan: 0 })
    render(<TodayPage />)
    expect(await screen.findByText(/Filing has not run since Tuesday: Obsidian was closed./)).toBeInTheDocument()
  })

  it('shows no line on the page where filing is not set up, though the service sent one', async () => {
    setFilingConfigured(false)
    serve({ line: 'Filed yesterday: 9 items.', filed_yesterday: 9, questions: 0, plan: 0 })
    render(<TodayPage />)
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByText(/Filed yesterday/)).not.toBeInTheDocument()
  })

  it('shows no line when the service sends none', async () => {
    serve(null)
    render(<TodayPage />)
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByRole('link', { name: 'Open To file' })).not.toBeInTheDocument()
  })
})
