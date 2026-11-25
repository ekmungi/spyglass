// The secondary pages against the sample-mode fixtures (the same shapes the real service sends):
// they must load, and accepting or dismissing a watch suggestion must change the list. The sample
// data must also hold every piece the page design shows: "what it says" texts, unpicked stories and votes.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { parseProfileReply } from '../api/client'
import type { ItemState, RadarItem, TodayResponse } from '../api/types'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import ProfilePage from './ProfilePage'
import PapersPage from './PapersPage'
import SettingsPage from './SettingsPage'
import SourcesPage from './SourcesPage'
import WatchPage from './WatchPage'
import { timing } from './sources/timing'
import { clearLoadCache } from './sources/useLoad'

beforeEach(() => {
  resetMockState()
  clearLoadCache()
  clearResourceCache()
  window.localStorage.clear()
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

describe('Watch page in sample mode', () => {
  it('moves an accepted suggestion into its category', async () => {
    render(<WatchPage />)
    const suggested = await screen.findByRole('region', { name: 'Suggested' }, { timeout: 4000 })
    expect(within(suggested).getByText('Arclight Endoscopy')).toBeInTheDocument()

    fireEvent.click(within(suggested).getByRole('button', { name: 'Accept Arclight Endoscopy' }))

    await waitFor(() => expect(screen.getByRole('region', { name: 'Suggested' })).not.toHaveTextContent('Arclight Endoscopy'), { timeout: 4000 })
    const category = screen.getByRole('region', { name: 'Imaging AI' })
    expect(within(category).getByText('Arclight Endoscopy')).toBeInTheDocument()
  })

  it('removes a dismissed suggestion from the list', async () => {
    render(<WatchPage />)
    const suggested = await screen.findByRole('region', { name: 'Suggested' }, { timeout: 4000 })
    fireEvent.click(within(suggested).getByRole('button', { name: 'Dismiss Quill Robotics' }))
    await waitFor(() => expect(screen.getByRole('region', { name: 'Suggested' })).not.toHaveTextContent('Quill Robotics'), { timeout: 4000 })
    // Dismissed names are kept out of the way, not deleted.
    expect(screen.getByText(/^Muted \(1\)$/)).toBeInTheDocument()
  })
})

describe('Sources page in sample mode', () => {
  it('lists feeds and collectors from the service shapes, and a collection runs to its end', async () => {
    const original = timing.pollMs
    timing.pollMs = 300
    try {
      render(<SourcesPage />)
      // The feeds have their own tab: the sample's failing feed is listed at once, the working ones behind a button.
      fireEvent.click(await screen.findByRole('tab', { name: /^Feeds/ }, { timeout: 4000 }))
      expect(await screen.findByText('Policy & Compute')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Show the working feeds' }))
      expect(screen.getByText('Signal Ledger')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Collect now' }))
      expect(await screen.findByText(/Collecting now/, {}, { timeout: 4000 })).toBeInTheDocument()
      await waitFor(() => expect(screen.getByRole('button', { name: 'Collect now' })).toBeEnabled(), { timeout: 9000 })
    } finally {
      timing.pollMs = original
    }
  }, 15000)
})

describe('Profile page in sample mode', () => {
  it('loads the profile from the {profile, examples} reply', async () => {
    render(<ProfilePage />)
    expect(await screen.findByDisplayValue(/Someone who follows AI closely and builds with AI agents/, {}, { timeout: 4000 })).toBeInTheDocument()
  })
})

describe('Settings and Find papers in sample mode', () => {
  it('lists the engines with the service fields', async () => {
    render(<SettingsPage />)
    // The engines have their own tab; the one the sample sets up is listed at once, the others behind a button.
    fireEvent.click(screen.getByRole('tab', { name: 'AI engines' }))
    expect((await screen.findAllByText('Claude (subscription)', {}, { timeout: 4000 })).length).toBeGreaterThan(0)
    expect(screen.getAllByText('OpenRouter').length).toBeGreaterThan(0)
  })

  it('offers example chips from the profile topics', async () => {
    render(<PapersPage />)
    expect(await screen.findByRole('group', { name: 'Topics from your profile' }, { timeout: 4000 })).toBeInTheDocument()
  })
})

describe('Sample data for the page design', () => {
  /** Call the sample service like the client does and read the JSON reply. */
  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await mockFetch(`/api/radar${path}`, init)
    expect(response.ok).toBe(true)
    return (await response.json()) as T
  }

  it('gives every item a "what it says" text but one, so both looks of a row can be seen', async () => {
    const { items } = await call<{ items: RadarItem[] }>('/feed?tier=all&limit=200')
    const without = items.filter((item) => !item.what)
    expect(without).toHaveLength(1)
    expect(items.length).toBeGreaterThan(1)
  }, 10000)

  it('gives the top and papers sections of the brief unpicked stories and the number judged', async () => {
    const { brief } = await call<TodayResponse>('/today')
    const section = (key: string) => brief?.sections.find((entry) => entry.key === key)
    for (const key of ['top', 'papers']) {
      const found = section(key)
      expect(found?.more?.length ?? 0).toBeGreaterThan(0)
      expect(found?.pool ?? 0).toBeGreaterThanOrEqual((found?.stories.length ?? 0) + (found?.more?.length ?? 0))
    }
    // Enough stories for the top section to need a second page (five on its first page).
    const top = section('top')
    expect((top?.stories.length ?? 0) + (top?.more?.length ?? 0)).toBeGreaterThan(5)
    // An unpicked story is never also a picked one.
    const picked = new Set(brief?.sections.flatMap((entry) => entry.stories.map((story) => story.item_id)))
    for (const entry of brief?.sections ?? []) for (const story of entry.more ?? []) expect(picked.has(story.item_id)).toBe(false)
    // Stories carry the item's "what it says" text.
    expect(top?.stories[0].what).toBeTruthy()
  }, 10000)

  it('records a vote on an unpicked story and takes it back, through the sample vote route', async () => {
    const { brief } = await call<TodayResponse>('/today')
    const unpicked = brief?.sections.find((entry) => entry.key === 'top')?.more?.[0]
    expect(unpicked).toBeDefined()
    const id = unpicked?.item_id ?? 0
    const vote = (value: string | null) => call<ItemState>(`/items/${id}/vote`, { method: 'POST', body: JSON.stringify({ vote: value }) })
    expect((await vote('more')).vote).toBe('more')
    const after = await call<TodayResponse>('/today')
    expect(after.brief?.sections.find((entry) => entry.key === 'top')?.more?.[0].state.vote).toBe('more')
    expect((await vote(null)).vote).toBeNull()
  }, 10000)
})

describe('parseProfileReply', () => {
  it('reads the service reply and tolerates a bare profile', () => {
    const wrapped = parseProfileReply({ profile: { version: 2, statement: 's', sections: [{ key: 'k', label: 'L', description: 'd' }], topics: [], avoid: ['x'] }, examples: { liked: ['a', ''], disliked: ['b'] } })
    expect(wrapped.profile.sections).toHaveLength(1)
    expect(wrapped.examples).toEqual({ liked: ['a'], disliked: ['b'] })
    const bare = parseProfileReply({ version: 1, statement: 't' })
    expect(bare.profile.statement).toBe('t')
    expect(bare.profile.sections).toEqual([])
    expect(bare.examples).toEqual({ liked: [], disliked: [] })
    expect(parseProfileReply(null).profile.version).toBe(0)
  })
})
