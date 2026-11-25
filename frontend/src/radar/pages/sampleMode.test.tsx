// The secondary pages against the sample-mode fixtures (the same shapes the real service sends):
// they must load, and watching or rejecting a watch suggestion must reach the sample service. The sample
// data must also hold every piece the page design shows: "what it says" texts, unpicked stories and votes.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { getWatch, parseProfileReply, patchWatchGroup, setSuggestionStatus } from '../api/client'
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
  it('watches a suggestion in place, and shows it in its group on the next visit', async () => {
    const first = render(<WatchPage />)
    const suggested = await screen.findByRole('region', { name: 'Suggested this month' }, { timeout: 4000 })
    const chip = within(suggested).getByRole('button', { name: 'Arclight Endoscopy, named in 4 items' })
    fireEvent.click(chip)
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    // The chip stays in its row on this visit; the next visit is opened once the service has agreed.
    await waitFor(() => expect(chip.closest('.rw-chip')).not.toHaveAttribute('aria-busy'), { timeout: 4000 })
    expect(within(suggested).getByRole('button', { name: 'Arclight Endoscopy, named in 4 items' })).toBe(chip)
    first.unmount()
    // The sample service recorded the change itself, not only the answer the page remembered.
    const followed = (await getWatch()).categories.flatMap((category) => category.entities)
    expect(followed.find((entity) => entity.name === 'Arclight Endoscopy')).toMatchObject({ status: 'active', category: 'Imaging AI' })

    render(<WatchPage />)
    const category = await screen.findByRole('group', { name: 'Imaging AI' }, { timeout: 4000 })
    expect(within(category).getByRole('button', { name: 'Arclight Endoscopy', pressed: true })).toBeInTheDocument()
  })

  it('strikes a rejected suggestion through in place and lists it under Not of interest at once', async () => {
    const first = render(<WatchPage />)
    const suggested = await screen.findByRole('region', { name: 'Suggested this month' }, { timeout: 4000 })
    fireEvent.click(within(suggested).getByRole('button', { name: 'Not of interest: Quill Robotics' }))
    const takeBack = within(suggested).getByRole('button', { name: 'Take back Quill Robotics' })
    await waitFor(() => expect(takeBack.closest('.rw-chip')).not.toHaveAttribute('aria-busy'), { timeout: 4000 })
    expect(screen.getByText('Not of interest (2)')).toBeInTheDocument()
    first.unmount()
    // The sample service recorded the change itself, not only the answer the page remembered.
    const reg = await getWatch()
    expect(reg.rejected.find((entity) => entity.name === 'Quill Robotics')).toMatchObject({ status: 'rejected' })
    expect(reg.suggested.map((entity) => entity.name)).not.toContain('Quill Robotics')

    render(<WatchPage />)
    expect(await screen.findByText('Not of interest (2)', undefined, { timeout: 4000 })).toBeInTheDocument()
    expect(within(await screen.findByRole('region', { name: 'Suggested this month' })).queryByText('Quill Robotics')).not.toBeInTheDocument()
  })
})

describe('Watch register in sample mode', () => {
  it('sends profile sections, suggestion counts and a rejected name like the service', async () => {
    const reg = await getWatch()
    expect(reg.sections.map((section) => section.key)).toContain('health')
    expect(reg.rejected.map((entity) => entity.name)).toEqual(['Dormant Analytics'])
    const arclight = reg.suggested.find((entity) => entity.name === 'Arclight Endoscopy')
    expect(arclight).toMatchObject({ section: 'health', count: 4, topic: null })
    expect(reg.suggested.some((entity) => entity.topic)).toBe(true)
    // Followed groups hold followed names only.
    const followed = reg.categories.flatMap((category) => category.entities)
    expect(followed.every((entity) => entity.status === 'active' || entity.status === 'muted')).toBe(true)
  })

  it('rejects a suggestion and takes it back through the status route', async () => {
    const rejected = await setSuggestionStatus([21], 'rejected')
    expect(rejected.changed).toEqual([21])
    expect(rejected.suggested.map((entity) => entity.name)).not.toContain('Quill Robotics')
    expect(rejected.rejected.map((entity) => entity.name)).toContain('Quill Robotics')

    const back = await setSuggestionStatus([21, 1], 'suggested') // id 1 is followed, so it is left alone
    expect(back.changed).toEqual([21])
    expect(back.suggested.map((entity) => entity.name)).toContain('Quill Robotics')
  })

  it('moves a group up and down', async () => {
    const before = (await getWatch()).categories.map((category) => category.name)
    const down = await patchWatchGroup({ category: before[0], action: 'down' })
    expect(down.categories.map((category) => category.name).slice(0, 2)).toEqual([before[1], before[0]])
    const up = await patchWatchGroup({ category: before[0], action: 'up' })
    expect(up.categories.map((category) => category.name)).toEqual(before)
  })
})

describe('Sources page in sample mode', () => {
  it('lists feeds and collectors from the service shapes, and a collection runs to its end', async () => {
    const original = timing.pollMs
    timing.pollMs = 300
    try {
      render(<SourcesPage />)
      // The sample's failing search marks the Searches tab, as a failing feed marks the Feeds tab.
      const searches = await screen.findByRole('tab', { name: /^Searches/ }, { timeout: 4000 })
      expect(within(searches).getByRole('img', { name: '1 search is failing' })).toBeInTheDocument()
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

  it('pages the watch list and Skim, gives From you no unpicked stories, and says some items wait to be judged', async () => {
    const { brief } = await call<TodayResponse>('/today')
    const section = (key: string) => brief?.sections.find((entry) => entry.key === key)
    const total = (key: string) => (section(key)?.stories.length ?? 0) + (section(key)?.more?.length ?? 0)
    // Three stories fit on a page of these sections, so both need a second page.
    expect(section('watch')?.more?.length ?? 0).toBeGreaterThan(0)
    expect(total('watch')).toBeGreaterThan(3)
    expect(section('skim')?.more?.length ?? 0).toBeGreaterThan(0)
    expect(section('skim')?.pool ?? 0).toBeGreaterThan(total('skim'))
    // As in a real brief, unpicked stories are never offered under From you.
    expect(section('from_you')?.more).toEqual([])
    expect(section('from_you')?.pool).toBe(section('from_you')?.stories.length)
    expect(brief?.degraded).toBe(true)
    expect(brief?.unjudged).toBe(3)
    expect(brief?.notice).toBe("3 collected items are still waiting to be judged, so a story may be missing from today's selection.")
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
