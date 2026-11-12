// Tests that filing stays out of sight where it is not set up (the service says `status.configured`
// is false, or leaves the field out): no File in vault control in the reader, no To file chip or view
// in the Feed (a link to it opens the normal Feed and loses the parameter), no filing line on Today,
// no "Waiting to be filed" on rows, and no "File this item in vault" under the assistant's answer.
// Where `configured` is true the controls are there.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACTION_LABELS } from '../assistant/actionLabels'
import { AssistantPanel } from '../assistant/AssistantPanel'
import { setAssistTarget } from '../assistant/assistStore'
import { resetConversations } from '../assistant/useThread'
import { setFetchForTesting } from '../api/transport'
import type { ItemDetail } from '../api/types'
import { FeedRow } from '../feed/FeedRow'
import { clearFeedCache } from '../feed/useFeed'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { buildItems } from '../mock/items'
import { FeedPage } from '../pages/FeedPage'
import { ReaderTopBar } from '../reader/ReaderTopBar'
import { resetFilingConfigured, setFilingConfigured } from '../state/filingConfigured'
import { resetFilingState } from '../state/filingState'
import { FilingLine } from '../today/FilingLine'

const api = vi.hoisted(() => ({ suggestTracksForItem: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

const detail = {
  id: 42,
  title: 'A title',
  headline: 'A headline',
  url: 'https://example.org/a',
  origin: 'Example Wire',
  published_at: null,
  state: { saved: false, opened: true, vote: null, from_user: false, captured_via: null, vault_path: null },
  story_sources: [],
  reader: null,
} as unknown as ItemDetail

/** The sample service, but GET /filing leaves out `status.configured` (an install that predates the flag). */
async function withoutFlag(url: string, init?: RequestInit): Promise<Response> {
  const response = await mockFetch(url, init)
  if (new URL(url, 'http://x').pathname.endsWith('/filing') && (init?.method ?? 'GET').toUpperCase() === 'GET') {
    const body = await response.json()
    const status = { ...body.status }
    delete status.configured
    return new Response(JSON.stringify({ ...body, status }), { status: 200 })
  }
  return response
}

beforeEach(() => {
  resetMockState()
  resetFilingState()
  resetConversations()
  clearResourceCache()
  clearFeedCache()
  window.localStorage.clear()
  window.history.replaceState(null, '', '/#/feed')
  api.suggestTracksForItem.mockReturnValue(new Promise(() => undefined))
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
  setAssistTarget(null)
  resetFilingConfigured()
})

describe('the reader top bar', () => {
  it('has no File in vault control when filing is not set up', () => {
    setFilingConfigured(false)
    render(<ReaderTopBar detail={detail} showPdf={false} onTogglePdf={() => undefined} />)
    expect(screen.getByRole('button', { name: /Follow/ })).toBeInTheDocument()
    expect(screen.queryByText('File in vault')).not.toBeInTheDocument()
  })

  it('has none while the answer is not known yet', () => {
    render(<ReaderTopBar detail={detail} showPdf={false} onTogglePdf={() => undefined} />)
    expect(screen.queryByText('File in vault')).not.toBeInTheDocument()
  })

  it('has the control when filing is set up', () => {
    setFilingConfigured(true)
    render(<ReaderTopBar detail={detail} showPdf={false} onTogglePdf={() => undefined} />)
    expect(screen.getByText('File in vault')).toBeInTheDocument()
  })
})

describe('the Feed', () => {
  it('has no To file chip when filing is not set up', async () => {
    setFilingConfigured(false)
    render(<FeedPage params={{}} />)
    await screen.findByRole('button', { name: 'Saved' })
    expect(screen.queryByRole('button', { name: /To file/ })).not.toBeInTheDocument()
  })

  it('has no To file chip when the service leaves the flag out', async () => {
    setFetchForTesting(withoutFlag)
    render(<FeedPage params={{}} />)
    await screen.findByRole('button', { name: 'Saved' })
    // Give the one request to GET /filing time to land, then check that nothing appeared.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400))
    })
    expect(screen.queryByRole('button', { name: /To file/ })).not.toBeInTheDocument()
  })

  it('has the To file chip when filing is set up', async () => {
    setFilingConfigured(true)
    render(<FeedPage params={{}} />)
    expect(await screen.findByRole('button', { name: /To file/ })).toBeInTheDocument()
  })

  it('opens the normal Feed for #/feed?filing=waiting and drops the parameter', async () => {
    window.history.replaceState(null, '', '/#/feed?filing=waiting')
    setFilingConfigured(false)
    render(<FeedPage params={{ filing: 'waiting' }} />)
    await waitFor(() => expect(window.location.hash).toBe('#/feed'))
    expect(screen.queryByRole('heading', { name: 'Waiting' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'File now' })).not.toBeInTheDocument()
  })

  it('keeps the parameter and shows the To file view when filing is set up', async () => {
    window.history.replaceState(null, '', '/#/feed?filing=waiting')
    setFilingConfigured(true)
    render(<FeedPage params={{ filing: 'waiting' }} />)
    expect(await screen.findByRole('heading', { name: 'Waiting' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/feed?filing=waiting')
  })
})

describe('a feed row', () => {
  const item = { ...buildItems()[0], filing: 'waiting' as const }
  const row = () => (
    <ul>
      <FeedRow item={item} index={0} selected={false} />
    </ul>
  )

  it('does not say "Waiting to be filed" when filing is not set up', () => {
    setFilingConfigured(false)
    render(row())
    expect(screen.queryByText(/Waiting to be filed/)).not.toBeInTheDocument()
  })

  it('says it when filing is set up', () => {
    setFilingConfigured(true)
    render(row())
    expect(screen.getByText(/Waiting to be filed/)).toBeInTheDocument()
  })
})

describe('the filing line on Today', () => {
  const text = 'Filed yesterday: 9 items. 2 questions are open.'

  it('is not shown when filing is not set up, even if the service sent a line', () => {
    setFilingConfigured(false)
    const { container } = render(<FilingLine text={text} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('is shown when filing is set up', () => {
    setFilingConfigured(true)
    render(<FilingLine text={text} />)
    expect(screen.getByText(/Filed yesterday: 9 items/)).toBeInTheDocument()
  })
})

describe('the assistant', () => {
  /** Ask "Which of my projects could this help?" about item 101 and wait for the answer. */
  async function askAboutProjects() {
    setAssistTarget({ kind: 'item', id: 101, title: 'Sample' })
    render(<AssistantPanel surface="reader" />)
    await screen.findByRole('button', { name: ACTION_LABELS.explain }, { timeout: 4000 })
    fireEvent.click(screen.getByRole('button', { name: 'More…' }))
    fireEvent.click(screen.getByRole('button', { name: 'Which of my projects could this help?' }))
    const panel = screen.getByRole('complementary', { name: 'Assistant' })
    await within(panel).findByText(/Nothing has been filed/, {}, { timeout: 9000 })
    // The answer is complete once it can be copied; only then are the buttons under it settled.
    await within(panel).findByRole('button', { name: 'Copy' }, { timeout: 9000 })
    return panel
  }

  it('offers no "File this item in vault" when filing is not set up', async () => {
    setFilingConfigured(false)
    const panel = await askAboutProjects()
    expect(within(panel).queryByRole('button', { name: 'File this item in vault' })).not.toBeInTheDocument()
  }, 20000)

  it('offers it when filing is set up', async () => {
    setFilingConfigured(true)
    const panel = await askAboutProjects()
    expect(within(panel).getByRole('button', { name: 'File this item in vault' })).toBeInTheDocument()
  }, 20000)
})
