// Tests for the Feed page's search box: a click on Feed in the rail must not bring the last search back.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { FeedPage } from './FeedPage'

beforeEach(() => {
  resetMockState()
  clearResourceCache()
  window.history.replaceState(null, '', '/#/feed')
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

describe('FeedPage search', () => {
  it('shows the search from the address, and clears the box when the address loses it', async () => {
    const { rerender } = render(<FeedPage params={{ q: 'robot' }} />)
    const box = (await screen.findByPlaceholderText(/Search titles/)) as HTMLInputElement
    expect(box.value).toBe('robot')
    rerender(<FeedPage params={{}} />)
    expect(box.value).toBe('')
    // The old search must not be written back into the address after the delay.
    await new Promise((resolve) => setTimeout(resolve, 450))
    expect(window.location.hash).toBe('#/feed')
    expect(box.value).toBe('')
  })

  it('writes what the reader types into the address once typing settles', async () => {
    render(<FeedPage params={{}} />)
    const box = await screen.findByPlaceholderText(/Search titles/)
    fireEvent.change(box, { target: { value: 'polyp' } })
    await waitFor(() => expect(window.location.hash).toBe('#/feed?q=polyp'), { timeout: 2000 })
  })
})

describe('FeedPage Filed filter', () => {
  it('has "Filed" in the Filters menu; choosing it puts filed=true in the address and shows only filed items', async () => {
    render(<FeedPage params={{}} />)
    await screen.findByPlaceholderText(/Search titles/)
    fireEvent.click(screen.getByRole('button', { name: /Filters/ }))
    expect(screen.getByRole('menuitem', { name: 'Filed' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Filed' }))
    await waitFor(() => expect(window.location.hash).toBe('#/feed?filed=true'))
  })

  it('sends filed=true to the service and shows whatever comes back', async () => {
    window.history.replaceState(null, '', '/#/feed?filed=true')
    render(<FeedPage params={{ filed: 'true' }} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Filters (1)' })).toBeInTheDocument())
    // The sample service filters on `filed`; one sample item starts out filed.
    expect(await screen.findByText('Notes from a talk on post-market surveillance for AI devices', {}, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.queryByText('Aster AI releases Aster 4 with a million-token context window')).not.toBeInTheDocument()
  })
})
