// Tests for the reader pane: stored markdown, fetch-on-demand, toolbar.
import { act, render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../../lib/api'
import { makeCard } from '../../test/fixtures'
import type { FetchJobState } from '../../lib/types'
import { JOB_POLL_MS } from '../../lib/useFulltextJob'
import { ReaderPane } from './ReaderPane'

const card = makeCard({ id: 7, title: 'Stored article', source: 'arXiv' })

const paneProps = {
  onBack: () => {},
  categories: [],
  onUpdate: () => {},
  onMerge: () => {},
  onCreateCategory: () => {},
  onSend: () => {},
}

/** A fetch job as the service reports it on the GET. */
const job = (
  status: FetchJobState['status'],
  error: string | null = null,
  cardId = 7,
): FetchJobState => ({ job_id: 1, card_id: cardId, status, error })

function stubFulltext(getBody: unknown, postBody?: unknown, getAfterPost?: unknown) {
  // Mirrors the service contract: POST only ENQUEUES and answers with the job;
  // the markdown and the job's progress both come from the follow-up GETs.
  let posted = false
  return vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method === 'POST') {
      posted = true
      return new Response(JSON.stringify(postBody), { status: 202 })
    }
    const body = posted && getAfterPost !== undefined ? getAfterPost : getBody
    return new Response(JSON.stringify(body), { status: 200 })
  })
}

/** Advance fake timers and flush the promises they schedule, inside act(). */
async function tick(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.spyOn(api, 'getSimilar').mockResolvedValue([])
  // Default: no distinct full card, so tests that don't care about the full-summary
  // fetch aren't broken by an unhandled rejection.
  vi.spyOn(api, 'getCard').mockResolvedValue(card)
})
afterEach(() => vi.unstubAllGlobals())

describe('ReaderPane', () => {
  it('shows a placeholder when no card is open', () => {
    render(<ReaderPane card={null} {...paneProps} />)
    expect(screen.getByText(/select an item to read/i)).toBeInTheDocument()
  })

  it('renders the stored markdown for the open card', async () => {
    vi.stubGlobal(
      'fetch',
      stubFulltext({ status: 'ok', markdown: '## Key finding\n\nBody text here.' }),
    )
    render(<ReaderPane card={card} {...paneProps} />)
    expect(await screen.findByText('Key finding')).toBeInTheDocument()
    expect(screen.getByText('Stored article')).toBeInTheDocument()
    // Header shows the brand label (from the URL hostname) plus the collector.
    expect(screen.getByText(/Example/)).toBeInTheDocument()
    expect(screen.getByText('via arXiv')).toBeInTheDocument()
  })

  it('shows the article age in the header with a full-timestamp tooltip', async () => {
    vi.stubGlobal('fetch', stubFulltext({ status: 'ok', markdown: 'Body.' }))
    const fiveHoursAgo = new Date(Date.now() - 5 * 3600_000).toISOString()
    render(
      <ReaderPane card={makeCard({ id: 8, title: 'Aged article', published_at: fiveHoursAgo })} {...paneProps} />,
    )
    const age = await screen.findByText(/5h ago/)
    expect(age).toHaveAttribute('title', expect.stringContaining('published'))
  })

  it('offers fetch-on-demand when nothing is stored, then shows the queued job through to its result', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal(
        'fetch',
        stubFulltext(
          { status: 'absent', markdown: null, job: null },
          job('queued'),
          { status: 'ok', markdown: 'Fetched body text.', job: job('done') },
        ),
      )
      render(<ReaderPane card={card} {...paneProps} />)
      await tick()
      fireEvent.click(screen.getByRole('button', { name: /fetch full text/i }))
      await tick()
      // The POST only enqueued; the pane shows progress and waits for the worker.
      expect(screen.getByText(/fetching full text/i)).toBeInTheDocument()

      await tick(JOB_POLL_MS)
      expect(screen.getByText('Fetched body text.')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows a fetch that was already in flight on a freshly mounted pane', async () => {
    // The regression this test guards against: this pane was rebuilt from scratch when
    // the user opened another card and came back, so it never witnessed the fetch starting.
    // It has to learn that from the server.
    vi.stubGlobal(
      'fetch',
      stubFulltext({ status: 'absent', markdown: null, job: job('running') }),
    )
    render(<ReaderPane card={card} {...paneProps} />)
    expect(await screen.findByText(/fetching full text/i)).toBeInTheDocument()
  })

  it('merges the freshly re-read card once the job completes', async () => {
    // The POST no longer carries the enrichment result, so the in-place card
    // merge happens on job completion and re-reads the card.
    vi.useFakeTimers()
    try {
      vi.stubGlobal(
        'fetch',
        stubFulltext(
          { status: 'absent', markdown: null, job: null },
          job('queued', null, 11),
          { status: 'ok', markdown: 'Fetched body text.', job: job('done', null, 11) },
        ),
      )
      const fresh = makeCard({ id: 11, summary: 'Fresh AI summary.', category: 'AI' })
      vi.spyOn(api, 'getCard').mockResolvedValue(fresh)
      const onMerge = vi.fn()
      render(
        <ReaderPane card={makeCard({ id: 11, summary: 'Old blurb.' })} {...paneProps} onMerge={onMerge} />,
      )
      await tick()
      fireEvent.click(screen.getByRole('button', { name: /fetch full text/i }))
      await tick(JOB_POLL_MS)
      expect(api.getCard).toHaveBeenCalledWith(11)
      expect(onMerge).toHaveBeenCalledWith(11, fresh)
    } finally {
      vi.useRealTimers()
    }
  })

  it('tells the caller a fetch was queued so the list can start showing its marker', async () => {
    vi.stubGlobal(
      'fetch',
      stubFulltext({ status: 'absent', markdown: null, job: null }, job('queued')),
    )
    const onFetchStart = vi.fn()
    render(<ReaderPane card={card} {...paneProps} onFetchStart={onFetchStart} />)
    fireEvent.click(await screen.findByRole('button', { name: /fetch full text/i }))
    expect(onFetchStart).toHaveBeenCalled()
  })

  it('surfaces a job the service was killed in the middle of', async () => {
    // An interrupted job stores no fulltext row at all, so without the job's own error this
    // would read as "never fetched".
    vi.stubGlobal(
      'fetch',
      stubFulltext({ status: 'absent', markdown: null, job: job('failed', 'interrupted') }),
    )
    render(
      <ReaderPane card={makeCard({ id: 7, summary: 'The card summary.' })} {...paneProps} />,
    )
    expect(await screen.findByText(/could not be fetched.*interrupted/i)).toBeInTheDocument()
  })

  it('falls back to the card summary when the fetch failed', async () => {
    vi.stubGlobal('fetch', stubFulltext({ status: 'failed', markdown: null }))
    render(
      <ReaderPane card={makeCard({ id: 8, summary: 'The card summary.' })} {...paneProps} />,
    )
    await waitFor(() => expect(screen.getByText(/could not be fetched/i)).toBeInTheDocument())
    // The summary now appears both in the pane header AND in the ReaderBody fallback.
    expect(screen.getAllByText('The card summary.').length).toBeGreaterThanOrEqual(1)
  })

  it('shows the generic fallback message when the failure carries no structured reason (regression)', async () => {
    vi.stubGlobal('fetch', stubFulltext({ status: 'failed', markdown: null }))
    render(
      <ReaderPane card={makeCard({ id: 8, summary: 'The card summary.' })} {...paneProps} />,
    )
    expect(await screen.findByText(/could not be fetched \(failed\)/i)).toBeInTheDocument()
  })

  it('surfaces the structured fetch-failure reason from the backend', async () => {
    vi.stubGlobal(
      'fetch',
      stubFulltext({
        status: 'failed',
        markdown: null,
        error: 'blocked at T0 (HTTP 403); T3 (browser) also failed: timeout',
        error_class: 'blocked',
        tier_reached: 'T3',
        detected_type: 'html',
        http_status: 403,
      }),
    )
    render(
      <ReaderPane card={makeCard({ id: 9, summary: 'The card summary.' })} {...paneProps} />,
    )
    expect(
      await screen.findByText(/blocked at T0 \(HTTP 403\); T3 \(browser\) also failed: timeout/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/reached tier T3/i)).toBeInTheDocument()
    expect(screen.getByText(/detected as html/i)).toBeInTheDocument()
  })

  it('fetches and shows the full summary on open', async () => {
    // The list card carries only a short preview; the reader must fetch the full
    // card and render its complete summary in the Summary panel.
    vi.stubGlobal('fetch', stubFulltext({ status: 'ok', markdown: 'Body.' }))
    const previewCard = makeCard({ id: 12, summary: 'Short preview…' })
    const fullSummary =
      'This is the complete, much longer summary that only the single-card endpoint returns.'
    vi.spyOn(api, 'getCard').mockResolvedValue(makeCard({ id: 12, summary: fullSummary }))
    render(<ReaderPane card={previewCard} {...paneProps} />)
    await screen.findByText('Body.')
    expect(api.getCard).toHaveBeenCalledWith(12)
    expect(await screen.findByText(fullSummary)).toBeInTheDocument()
  })

  it('shows the toolbar and archives through onUpdate', async () => {
    vi.stubGlobal('fetch', stubFulltext({ status: 'ok', markdown: 'Body.' }))
    const onUpdate = vi.fn()
    render(<ReaderPane card={card} {...paneProps} onUpdate={onUpdate} />)
    await screen.findByText('Body.')
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
    expect(onUpdate).toHaveBeenCalledWith(7, { state: 'dismissed' })
  })

  it('applies a relevance choice through onMerge (net-change handled server-side)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'PATCH') {
          return new Response(JSON.stringify({ relevance: 'high', relevance_override: true }), {
            status: 200,
          })
        }
        return new Response(JSON.stringify({ status: 'ok', markdown: 'Body.' }), { status: 200 })
      }),
    )
    const onMerge = vi.fn()
    render(
      <ReaderPane
        card={makeCard({ id: 9, relevance: 'medium', relevance_ai: 'medium' })}
        {...paneProps}
        onMerge={onMerge}
      />,
    )
    await screen.findByText('Body.')
    fireEvent.click(screen.getByRole('button', { name: /relevance: medium/i }))
    fireEvent.click(screen.getByRole('button', { name: 'High' }))
    await waitFor(() =>
      expect(onMerge).toHaveBeenCalledWith(9, { relevance: 'high', relevance_override: true }),
    )
  })
})
