// Tests for the Brief tab: list, generate-now flow, brief reader, send-to-Claude.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from '../lib/api'
import { makeBrief } from '../test/fixtures'
import { BriefTab } from './BriefTab'

afterEach(() => vi.restoreAllMocks())

/** Render the tab with stubbed callbacks; returns the spies. */
function renderTab() {
  const onOpenClaude = vi.fn()
  render(<BriefTab onOpenClaude={onOpenClaude} />)
  return { onOpenClaude }
}

describe('BriefTab', () => {
  it('lists briefs with title, covers window, and article counts', async () => {
    vi.spyOn(api, 'getBriefs').mockResolvedValue([
      makeBrief({ id: 2, title: 'Daily Brief — Jul 1, 2026', item_count: 5, low_count: 3 }),
      makeBrief({ id: 1, title: 'Daily Brief — Jun 30, 2026', item_count: 1, low_count: 0 }),
    ])
    renderTab()
    expect(await screen.findByText('Daily Brief — Jul 1, 2026')).toBeInTheDocument()
    expect(screen.getByText('Daily Brief — Jun 30, 2026')).toBeInTheDocument()
    expect(screen.getByText(/5 articles, 3 also noticed/)).toBeInTheDocument()
    expect(screen.getByText(/1 article\b/)).toBeInTheDocument()
  })

  it('explains the automatic composition when no briefs exist yet', async () => {
    vi.spyOn(api, 'getBriefs').mockResolvedValue([])
    renderTab()
    expect(await screen.findByText(/composes .* automatically/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate now/i })).toBeInTheDocument()
  })

  it('surfaces a failed list load as an error message', async () => {
    vi.spyOn(api, 'getBriefs').mockRejectedValue(new Error('GET /api/briefs failed: 500'))
    renderTab()
    expect(await screen.findByText(/failed: 500/)).toBeInTheDocument()
  })

  it('opens a brief on click and returns via Back to list', async () => {
    vi.spyOn(api, 'getBriefs').mockResolvedValue([makeBrief({ id: 2 })])
    vi.spyOn(api, 'getBrief').mockResolvedValue(
      makeBrief({ id: 2, markdown: '# Heading\n\nBrief body text.' }),
    )
    renderTab()
    fireEvent.click(await screen.findByText('Daily Brief — Jul 1, 2026'))
    expect(await screen.findByText('Brief body text.')).toBeInTheDocument()
    expect(api.getBrief).toHaveBeenCalledWith(2)
    fireEvent.click(screen.getByRole('button', { name: /back to list/i }))
    expect(screen.queryByText('Brief body text.')).not.toBeInTheDocument()
    expect(screen.getByText('Daily Brief — Jul 1, 2026')).toBeInTheDocument()
  })

  it('generates a brief, prepends it to the list, and opens it', async () => {
    vi.spyOn(api, 'getBriefs').mockResolvedValue([])
    // The composed response carries light summaries (no markdown); the reader opens
    // the newest by fetching it in full.
    vi.spyOn(api, 'getBrief').mockResolvedValue(makeBrief({ id: 9, markdown: 'Fresh brief body.' }))
    let resolve!: (result: Awaited<ReturnType<typeof api.generateBrief>>) => void
    vi.spyOn(api, 'generateBrief').mockReturnValue(
      new Promise((res) => {
        resolve = res
      }),
    )
    renderTab()
    const button = await screen.findByRole('button', { name: /generate now/i })
    fireEvent.click(button)
    // While the POST is in flight, the button is disabled and shows progress.
    expect(screen.getByRole('button', { name: /generating/i })).toBeDisabled()
    resolve({ composed: [makeBrief({ id: 9 })], status: 'composed', held: 0 })
    // The freshly composed brief is fetched in full and opened.
    expect(await screen.findByText('Fresh brief body.')).toBeInTheDocument()
    expect(api.getBrief).toHaveBeenCalledWith(9)
    // Back to list shows the new brief prepended.
    fireEvent.click(screen.getByRole('button', { name: /back to list/i }))
    expect(screen.getByText('Daily Brief — Jul 1, 2026')).toBeInTheDocument()
  })

  it('shows a quiet notice when there is nothing to brief', async () => {
    vi.spyOn(api, 'getBriefs').mockResolvedValue([])
    vi.spyOn(api, 'generateBrief').mockResolvedValue({ composed: [], status: 'empty', held: 0 })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /generate now/i }))
    expect(await screen.findByText('Nothing new to brief.')).toBeInTheDocument()
  })

  it('reports held days when a due day is paused instead of "nothing to brief"', async () => {
    vi.spyOn(api, 'getBriefs').mockResolvedValue([])
    // A day was due but its bucket paused (heavy day): composed is empty yet held > 0.
    vi.spyOn(api, 'generateBrief').mockResolvedValue({ composed: [], status: 'empty', held: 1 })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /generate now/i }))
    expect(await screen.findByText(/1 day held/i)).toBeInTheDocument()
    expect(screen.queryByText('Nothing new to brief.')).not.toBeInTheDocument()
  })

  it('shows the paused message when the LLM is unreachable', async () => {
    vi.spyOn(api, 'getBriefs').mockResolvedValue([])
    vi.spyOn(api, 'generateBrief').mockRejectedValue(new api.BriefUnavailableError())
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /generate now/i }))
    expect(
      await screen.findByText(
        'Brief paused — the LLM is unreachable; items are held for the next run.',
      ),
    ).toBeInTheDocument()
  })

  it('recompose swaps the open brief markdown in place', async () => {
    vi.spyOn(api, 'getBriefs').mockResolvedValue([makeBrief({ id: 2 })])
    vi.spyOn(api, 'getBrief').mockResolvedValue(makeBrief({ id: 2, markdown: 'Old body.' }))
    vi.spyOn(api, 'recomposeBrief').mockResolvedValue(
      makeBrief({ id: 2, markdown: 'Fresh recomposed body.' }),
    )
    renderTab()
    fireEvent.click(await screen.findByText('Daily Brief — Jul 1, 2026'))
    expect(await screen.findByText('Old body.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /recompose/i }))
    expect(await screen.findByText('Fresh recomposed body.')).toBeInTheDocument()
    expect(screen.queryByText('Old body.')).not.toBeInTheDocument()
  })

  it('sends the brief card ids and prompt to Claude', async () => {
    vi.spyOn(api, 'getBriefs').mockResolvedValue([makeBrief({ id: 2 })])
    vi.spyOn(api, 'getBrief').mockResolvedValue(
      makeBrief({ id: 2, markdown: 'Read [A](card:11) and [B](card:22).' }),
    )
    const { onOpenClaude } = renderTab()
    fireEvent.click(await screen.findByText('Daily Brief — Jul 1, 2026'))
    fireEvent.click(await screen.findByRole('button', { name: /open in claude/i }))
    expect(onOpenClaude).toHaveBeenCalledWith(
      [11, 22],
      "Use the spyglass skill: discuss today's Spyglass brief with me; its referenced cards are loaded.",
    )
  })
})
