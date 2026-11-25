// The secondary pages against the sample-mode fixtures (the same shapes the real service sends):
// they must load, and watching or rejecting a watch suggestion must change the list by the next visit.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { getWatch, parseProfileReply, patchWatchGroup, setSuggestionStatus } from '../api/client'
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

    render(<WatchPage />)
    const category = await screen.findByRole('group', { name: 'Imaging AI' }, { timeout: 4000 })
    expect(within(category).getByRole('button', { name: 'Arclight Endoscopy', pressed: true })).toBeInTheDocument()
  })

  it('strikes a rejected suggestion through in place, and lists it under Not of interest on the next visit', async () => {
    const first = render(<WatchPage />)
    const suggested = await screen.findByRole('region', { name: 'Suggested this month' }, { timeout: 4000 })
    fireEvent.click(within(suggested).getByRole('button', { name: 'Not of interest: Quill Robotics' }))
    const takeBack = within(suggested).getByRole('button', { name: 'Take back Quill Robotics' })
    await waitFor(() => expect(takeBack.closest('.rw-chip')).not.toHaveAttribute('aria-busy'), { timeout: 4000 })
    expect(screen.getByText('Not of interest (1)')).toBeInTheDocument()
    first.unmount()

    render(<WatchPage />)
    expect(await screen.findByText('Not of interest (2)', undefined, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Take back Quill Robotics' })).toBeInTheDocument()
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
      expect(await screen.findByText('Signal Ledger', {}, { timeout: 4000 })).toBeInTheDocument()
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
    expect((await screen.findAllByText('Claude (subscription)', {}, { timeout: 4000 })).length).toBeGreaterThan(0)
    expect(screen.getAllByText('OpenRouter').length).toBeGreaterThan(0)
  })

  it('offers example chips from the profile topics', async () => {
    render(<PapersPage />)
    expect(await screen.findByRole('group', { name: 'Topics from your profile' }, { timeout: 4000 })).toBeInTheDocument()
  })
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
