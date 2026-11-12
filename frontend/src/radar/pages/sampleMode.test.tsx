// The secondary pages against the sample-mode fixtures (the same shapes the real service sends):
// they must load, and accepting or dismissing a watch suggestion must change the list.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { parseProfileReply } from '../api/client'
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
