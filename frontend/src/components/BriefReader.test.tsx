// Tests for the brief reader: section split rendering, collapsible
// References / Also noticed panels, and the Recompose action states.
// Also tests the unified adaptive Claude control, which replaced the
// standalone "Send to Claude" button + the narrative's selection bar.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from '../lib/api'
import { parseCardIds } from '../lib/briefLinks'
import { makeBrief } from '../test/fixtures'
import { BriefReader } from './BriefReader'

afterEach(() => vi.restoreAllMocks())

// A current-format brief: lead, one theme, References, Also noticed.
const SECTIONED = [
  'Lead paragraph about the day.',
  '',
  '## Agentic AI',
  '',
  'Theme prose citing [Alpha](card:1).',
  '',
  '## References',
  '',
  '- [Ref one](card:1) — Feed A',
  '- [Ref two](card:2) — Feed B',
  '',
  '## Also noticed',
  '',
  '- [Tail one](card:3)',
  '- [Tail two](card:4)',
].join('\n')

// A brief whose narrative contains an actual `- ` bullet (with a card: link) so a
// grip renders — SECTIONED's narrative is prose-only (the "## Agentic AI" body is
// a paragraph, not a bullet list).
const WITH_BULLET = [
  'Lead paragraph about the day.',
  '',
  '## Agentic AI',
  '',
  '- Alpha ships a new agent citing [Alpha](card:1).',
].join('\n')

/** Render the reader with stubbed callbacks; returns the spies. */
function renderReader(markdown: string, onRecomposed = vi.fn()) {
  const onOpenClaude = vi.fn()
  render(
    <BriefReader
      brief={makeBrief({ id: 7, markdown })}
      onBack={() => {}}
      onOpenClaude={onOpenClaude}
      onRecomposed={onRecomposed}
    />,
  )
  return { onOpenClaude, onRecomposed }
}

describe('BriefReader sections', () => {
  it('renders the narrative and both tail panels for a sectioned brief', () => {
    renderReader(SECTIONED)
    expect(screen.getByText('Lead paragraph about the day.')).toBeInTheDocument()
    expect(screen.getByText('Agentic AI')).toBeInTheDocument()
    // References panel is expanded by default: its items are visible.
    expect(screen.getByText('Ref one')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /collapse references/i })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    // Also noticed is collapsed by default with the parsed count in the header.
    expect(screen.getByText(/also noticed \(2\)/i)).toBeInTheDocument()
    expect(screen.queryByText('Tail one')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /expand also noticed/i })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('toggles the Also noticed panel open and closed', () => {
    renderReader(SECTIONED)
    fireEvent.click(screen.getByRole('button', { name: /expand also noticed/i }))
    expect(screen.getByText('Tail one')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /collapse also noticed/i }))
    expect(screen.queryByText('Tail one')).not.toBeInTheDocument()
  })

  it('toggles the References panel closed', () => {
    renderReader(SECTIONED)
    fireEvent.click(screen.getByRole('button', { name: /collapse references/i }))
    expect(screen.queryByText('Ref one')).not.toBeInTheDocument()
  })

  it('renders an old-format brief (no sections) entirely as narrative without panels', () => {
    renderReader('# Old brief\n\nPlain prose with [A](card:1).')
    expect(screen.getByText(/plain prose/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /references/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/also noticed/i)).not.toBeInTheDocument()
  })

  it('tolerates a brief without an Also noticed section', () => {
    renderReader('Lead.\n\n## References\n\n- [Solo ref](card:9)')
    expect(screen.getByText('Solo ref')).toBeInTheDocument()
    expect(screen.queryByText(/also noticed/i)).not.toBeInTheDocument()
  })

  it('card links inside the panels still route through onCardLink', () => {
    const onCardLink = vi.fn()
    render(
      <BriefReader
        brief={makeBrief({ id: 7, markdown: SECTIONED })}
        onBack={() => {}}
        onOpenClaude={() => {}}
        onCardLink={onCardLink}
      />,
    )
    fireEvent.click(screen.getByText('Ref two'))
    expect(onCardLink).toHaveBeenCalledWith(2)
  })

  it('recomposes the brief and hands the fresh brief to onRecomposed', async () => {
    const fresh = makeBrief({ id: 7, markdown: 'Recomposed body.' })
    vi.spyOn(api, 'recomposeBrief').mockResolvedValue(fresh)
    const { onRecomposed } = renderReader(SECTIONED)
    fireEvent.click(screen.getByRole('button', { name: /recompose/i }))
    // In flight: the button shows progress and is disabled.
    expect(screen.getByRole('button', { name: /recomposing/i })).toBeDisabled()
    await screen.findByRole('button', { name: /^recompose$/i })
    expect(api.recomposeBrief).toHaveBeenCalledWith(7)
    expect(onRecomposed).toHaveBeenCalledWith(fresh)
  })

  it('shows the paused message when recompose answers 503', async () => {
    vi.spyOn(api, 'recomposeBrief').mockRejectedValue(new api.BriefUnavailableError())
    renderReader(SECTIONED)
    fireEvent.click(screen.getByRole('button', { name: /recompose/i }))
    expect(
      await screen.findByText(
        'Brief paused — the LLM is unreachable; items are held for the next run.',
      ),
    ).toBeInTheDocument()
  })
})

describe('BriefReader unified Claude control', () => {
  it('launches the whole brief directly when nothing is selected', () => {
    const { onOpenClaude } = renderReader(WITH_BULLET)
    const button = screen.getByRole('button', { name: /open in claude/i })
    fireEvent.click(button)
    expect(onOpenClaude).toHaveBeenCalledTimes(1)
    expect(onOpenClaude).toHaveBeenCalledWith(
      parseCardIds(WITH_BULLET),
      "Use the spyglass skill: discuss today's Spyglass brief with me; its referenced cards are loaded.",
    )
    expect(screen.queryByTestId('brief-session-popover-backdrop')).not.toBeInTheDocument()
  })

  it('adapts to the scoped control and opens the popover once a bullet is selected', () => {
    const { onOpenClaude } = renderReader(WITH_BULLET)
    fireEvent.click(screen.getAllByLabelText('Select this bullet')[0])
    expect(screen.getByRole('button', { name: /open 1 in claude/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /open 1 in claude/i }))
    expect(screen.getByTestId('brief-session-popover-backdrop')).toBeInTheDocument()
    expect(onOpenClaude).not.toHaveBeenCalled()
  })

  it('clears the selection and reverts to the whole-brief control', () => {
    renderReader(WITH_BULLET)
    fireEvent.click(screen.getAllByLabelText('Select this bullet')[0])
    expect(screen.getByRole('button', { name: /open 1 in claude/i })).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Clear selection'))
    expect(screen.getByRole('button', { name: /^open in claude$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /open 1 in claude/i })).not.toBeInTheDocument()
  })

  it('deselects the bullets after launching a session (issue #6)', () => {
    const { onOpenClaude } = renderReader(WITH_BULLET)
    fireEvent.click(screen.getAllByLabelText('Select this bullet')[0])
    fireEvent.click(screen.getByRole('button', { name: /open 1 in claude/i }))
    // The scope popover is open; Launch (default Combine) fires the session.
    fireEvent.click(screen.getByRole('button', { name: /^launch$/i }))
    expect(onOpenClaude).toHaveBeenCalledTimes(1)
    // Launch consumed the selection: the control reverts to the whole-brief affordance
    // and the popover is gone.
    expect(screen.getByRole('button', { name: /^open in claude$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /open 1 in claude/i })).not.toBeInTheDocument()
    expect(screen.queryByTestId('brief-session-popover-backdrop')).not.toBeInTheDocument()
  })
})
