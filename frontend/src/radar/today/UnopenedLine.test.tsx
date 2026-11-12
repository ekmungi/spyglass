// The line on Today about briefs that were never opened.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { TodayPage } from '../pages/TodayPage'
import { unopenedParts } from './unopened'
import { UnopenedLine } from './UnopenedLine'

beforeEach(() => {
  resetMockState()
  clearResourceCache()
  window.localStorage.clear()
  window.history.replaceState(null, '', '/#/today')
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

describe('unopenedParts', () => {
  it('names dates in the order they happened, giving the month once at the end of a run', () => {
    expect(unopenedParts(['2026-11-11', '2026-11-10']).map((part) => part.text)).toEqual(['10', '11 November'])
    expect(unopenedParts(['2026-11-11', '2026-11-08', '2026-11-10']).map((part) => part.text)).toEqual(['8', '10', '11 November'])
    expect(unopenedParts(['2026-11-02', '2026-10-30']).map((part) => part.text)).toEqual(['30 October', '2 November'])
    expect(unopenedParts(['2026-11-11', '2026-11-11']).map((part) => part.text)).toEqual(['11 November'])
    expect(unopenedParts([])).toEqual([])
  })
})

describe('UnopenedLine', () => {
  const text = () => document.querySelector('.r-masthead__unopened')?.textContent

  it('says "the brief of 11 November" for one day, with the date as a link to that day', () => {
    render(<UnopenedLine days={['2026-11-11']} />)
    expect(text()).toBe('You have not opened the brief of 11 November')
    const link = screen.getByRole('link', { name: '11 November' })
    expect(link).toHaveAttribute('href', '#/today/2026-11-11')
    fireEvent.click(link)
    expect(window.location.hash).toBe('#/today/2026-11-11')
  })

  it('says "the briefs of 10 and 11 November" for two days, each date its own link', () => {
    render(<UnopenedLine days={['2026-11-11', '2026-11-10']} />)
    expect(text()).toBe('You have not opened the briefs of 10 and 11 November')
    expect(screen.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(['#/today/2026-11-10', '#/today/2026-11-11'])
  })

  it('lists three days with commas and "and"', () => {
    render(<UnopenedLine days={['2026-11-11', '2026-11-10', '2026-11-08']} />)
    expect(text()).toBe('You have not opened the briefs of 8, 10 and 11 November')
  })

  it('shows nothing when there are none', () => {
    const { container } = render(<UnopenedLine days={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('Today', () => {
  it('shows the line under the meta line when the service lists unopened days, and nothing otherwise', async () => {
    setFetchForTesting(mockFetch)
    render(<TodayPage />)
    await waitFor(() => expect(document.querySelector('.r-masthead__unopened')).not.toBeNull(), { timeout: 4000 })
    expect(document.querySelector('.r-masthead__unopened')?.textContent).toMatch(/^You have not opened the briefs of /)
    expect(document.querySelectorAll('.r-masthead__unopened a')).toHaveLength(2)
    cleanup()
    clearResourceCache()
    setFetchForTesting(async (url, init) => {
      const response = await mockFetch(url, init)
      if (!url.endsWith('/today')) return response
      return new Response(JSON.stringify({ ...(await response.json()), unopened_days: [] }), { status: 200 })
    })
    render(<TodayPage />)
    await screen.findByText('Earlier briefs', {}, { timeout: 4000 })
    expect(document.querySelector('.r-masthead__unopened')).toBeNull()
  })
})
