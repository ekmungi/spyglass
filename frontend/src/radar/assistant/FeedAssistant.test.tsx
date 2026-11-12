// The assistant panel on the Feed: its own header, starters and placeholder; answers whose [#id]
// citations are links named by headline; and "Show these in the Feed" under an answer.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { AssistantPanel } from './AssistantPanel'
import { setAssistTarget } from './assistStore'
import { MessageView } from './MessageView'
import { mergeRetrieved, resetConversations, type UiMessage } from './useThread'

beforeEach(() => {
  resetMockState()
  resetConversations()
  clearResourceCache()
  window.localStorage.clear()
  window.history.replaceState(null, '', '/#/feed')
  setFetchForTesting(mockFetch)
  setAssistTarget({ kind: 'feed' })
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
  setAssistTarget(null)
})

describe('AssistantPanel about the feed', () => {
  it('says "About your feed", offers the two feed starters and the feed placeholder', async () => {
    render(<AssistantPanel surface="feed" />)
    const panel = screen.getByRole('complementary', { name: 'Assistant' })
    expect(within(panel).getByText('About your feed')).toBeInTheDocument()
    expect(await within(panel).findByRole('button', { name: 'What matters most this week?' }, { timeout: 4000 })).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Which themes run through my feed?' })).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Explain' })).not.toBeInTheDocument()
    expect(within(panel).getByLabelText('Message the assistant')).toHaveAttribute('placeholder', 'Ask your feed, or describe what to find…')
  })

  it('answers with citations as links named by headline, and "Show these in the Feed" filters the Feed to them', async () => {
    render(<AssistantPanel surface="feed" />)
    const panel = screen.getByRole('complementary', { name: 'Assistant' })
    fireEvent.click(await within(panel).findByRole('button', { name: 'What matters most this week?' }, { timeout: 4000 }))
    const show = await within(panel).findByRole('button', { name: 'Show these in the Feed' }, { timeout: 12000 })
    const links = [...panel.querySelectorAll<HTMLAnchorElement>('a.r-cite')]
    expect(links.length).toBeGreaterThan(0)
    // A citation reads as the item's headline, not as its number.
    expect(links.every((link) => !/^#\d+$/.test(link.textContent ?? '') && link.textContent !== '')).toBe(true)
    const ids = links.map((link) => Number(link.getAttribute('href')?.replace('#/item/', '')))
    fireEvent.click(show)
    expect(window.location.hash).toBe(`#/feed?cited=${[...new Set(ids)].join('%2C')}`)
  }, 20000)
})

const answer = (content: string, extra: Partial<UiMessage> = {}): UiMessage => ({
  key: 'a1',
  id: 7,
  role: 'assistant',
  content,
  selection: null,
  action: null,
  status: 'done',
  error: null,
  ...extra,
})

describe('MessageView in a feed conversation', () => {
  const shown = new Set([12, 40])
  const feed = (showInFeed: (ids: number[]) => void) => ({ label: (id: number) => (id === 12 ? 'Clearance news' : null), shown, showInFeed })

  it('offers "Show these in the Feed" with the cited ids in cited order, leaving out ids that were never shown', () => {
    const calls: number[][] = []
    render(<MessageView message={answer('First [#40], then [#12], and a made-up [#999].')} onRetry={() => undefined} feed={feed((ids) => calls.push(ids))} />)
    fireEvent.click(screen.getByRole('button', { name: 'Show these in the Feed' }))
    expect(calls).toEqual([[40, 12]])
    expect(screen.getByRole('link', { name: 'Clearance news' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '#40' })).toBeInTheDocument()
  })

  it('offers nothing when the answer cites nothing, is still streaming, or the conversation is not about the feed', () => {
    const { rerender } = render(<MessageView message={answer('No citations here.')} onRetry={() => undefined} feed={feed(() => undefined)} />)
    expect(screen.queryByRole('button', { name: 'Show these in the Feed' })).not.toBeInTheDocument()
    rerender(<MessageView message={answer('Cited [#12]', { status: 'streaming' })} onRetry={() => undefined} feed={feed(() => undefined)} />)
    expect(screen.queryByRole('button', { name: 'Show these in the Feed' })).not.toBeInTheDocument()
    rerender(<MessageView message={answer('Cited [#12]')} onRetry={() => undefined} />)
    expect(screen.queryByRole('button', { name: 'Show these in the Feed' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})

describe('mergeRetrieved', () => {
  it('adds new items and lets a newer headline replace an older one', () => {
    const merged = mergeRetrieved([{ id: 1, headline: 'Old' }, { id: 2, headline: 'Two' }], [{ id: 1, headline: 'New' }, { id: 3, headline: 'Three' }])
    expect(merged).toEqual([{ id: 2, headline: 'Two' }, { id: 1, headline: 'New' }, { id: 3, headline: 'Three' }])
    expect(mergeRetrieved(merged, undefined)).toBe(merged)
  })
})

