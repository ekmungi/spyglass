// Tests for the Usage group of Settings: the 7-day table, the explanation, and the empty and error states.
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../../api/transport'
import { mockFetch } from '../../mock'
import { UsageSection } from './UsageSection'
import { purposeLabel } from './usageLabels'

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

describe('UsageSection', () => {
  it('shows a table by job with the cached share, and explains what a cached read is', async () => {
    setFetchForTesting(mockFetch)
    render(<UsageSection />)
    const table = await screen.findByRole('table', { name: 'AI usage in the last 7 days' }, { timeout: 3000 })
    expect(within(table).getByRole('rowheader', { name: 'Sorting new items' })).toBeInTheDocument()
    expect(within(table).getByRole('rowheader', { name: 'All jobs' })).toBeInTheDocument()
    expect(within(table).getAllByText(/\d+%/).length).toBeGreaterThan(2)
    expect(screen.getByText(/re-reads it from its cache at a fraction of the cost/)).toBeInTheDocument()
  })

  it('says so when nothing was used', async () => {
    setFetchForTesting(async () => new Response(JSON.stringify({ days: 7, since: '', totals: {}, per_day: [], by_purpose: [], by_model: [], conversations: [] }), { status: 200 }))
    render(<UsageSection />)
    expect(await screen.findByText('Nothing used in the last 7 days.')).toBeInTheDocument()
  })

  it('shows a plain error when the report cannot be loaded', async () => {
    setFetchForTesting(async () => new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }))
    render(<UsageSection />)
    expect(await screen.findByText(/Usage could not be loaded/)).toBeInTheDocument()
  })

  it('names jobs in plain words and passes an unknown one through', () => {
    expect(purposeLabel('digest')).toBe('Reading and summarising items')
    expect(purposeLabel('something_new')).toBe('something_new')
  })
})
