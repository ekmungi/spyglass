// The section chips on the Feed carry the profile's own section names: the built-in defaults before
// the profile has loaded, the profile's labels (never shortened) after, with its description as the tooltip.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearResourceCache } from '../hooks/useResource'
import { DEFAULT_SECTIONS } from '../lib/sections'
import { mockFetch, resetMockState } from '../mock'
import { FeedPage } from './FeedPage'

const PROFILE_SECTIONS = [
  { key: 'models', label: 'Models, platforms and tooling', description: 'Releases that change what you can build.' },
  { key: 'health', label: 'Healthcare AI & medtech', description: 'Clinical AI and devices.' },
]

/** The sample service, except that GET /profile answers with `PROFILE_SECTIONS`. */
const withProfile = async (url: string, init?: RequestInit): Promise<Response> => {
  if (url.includes('/profile') && (init?.method ?? 'GET') === 'GET') {
    const body = { profile: { version: 1, statement: '', sections: PROFILE_SECTIONS, topics: [], avoid: [] }, examples: { liked: [], disliked: [] } }
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  return mockFetch(url, init)
}

beforeEach(() => {
  resetMockState()
  clearResourceCache()
  window.history.replaceState(null, '', '/#/feed')
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

/** The names of the section chips (everything after "All sections"). */
function chipNames(): string[] {
  const group = screen.getByRole('group', { name: 'Sections' })
  return within(group)
    .getAllByRole('button')
    .map((button) => button.textContent ?? '')
    .slice(1)
}

describe('Feed section chips', () => {
  it('show the default profile labels in full before the profile has loaded', () => {
    setFetchForTesting(() => new Promise<Response>(() => undefined))
    render(<FeedPage params={{}} />)
    expect(chipNames()).toEqual(DEFAULT_SECTIONS.map((section) => section.label))
    expect(chipNames()).toEqual([
      'Models & platforms',
      'Labs & research',
      'Building with agents',
      'Healthcare AI & medtech',
      'Industry & use cases',
      'Where AI is heading',
    ])
  })

  it('show exactly the profile labels, in full, with the description as the tooltip, once it has loaded', async () => {
    setFetchForTesting(withProfile)
    render(<FeedPage params={{}} />)
    await waitFor(() => expect(chipNames()).toEqual(PROFILE_SECTIONS.map((section) => section.label)))
    const chip = within(screen.getByRole('group', { name: 'Sections' })).getByRole('button', { name: 'Healthcare AI & medtech' })
    expect(chip).toHaveAttribute('title', 'Clinical AI and devices.')
  })

  it('equal the sample profile labels after the sample service answers', async () => {
    setFetchForTesting(mockFetch)
    render(<FeedPage params={{}} />)
    await screen.findByPlaceholderText(/Search titles/)
    await waitFor(() => expect(within(screen.getByRole('group', { name: 'Sections' })).getByRole('button', { name: 'Where AI is heading' })).toHaveAttribute('title', expect.stringContaining('Sample description')))
    expect(chipNames()).toEqual(DEFAULT_SECTIONS.map((section) => section.label))
  })
})
