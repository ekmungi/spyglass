// Tests for the Inbox tab: the shared papers, the run line, and the Claude actions.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from '../lib/api'
import type { InboxData } from '../lib/types'
import { INBOX_PROMPT, runLine } from '../lib/inbox'
import { InboxTab } from './InboxTab'

const PAPER = {
  entry_id: 1,
  card_id: 7,
  title: 'Agents in radiology',
  url: 'https://arxiv.org/abs/2410.00001',
  summary: 'A benchmark of agentic triage.',
  note_path: 'Papers/Agents in radiology.md',
  message_text: 'look at this for Spyglass',
  full_text: false,
  filed: true,
  shared: 2,
  added_at: new Date().toISOString(),
}

function stubInbox(data: InboxData) {
  vi.spyOn(api, 'getInbox').mockResolvedValue(data)
}

afterEach(() => vi.restoreAllMocks())

describe('InboxTab', () => {
  it('lists papers with the user\'s words, the summary and what is missing', async () => {
    stubInbox({ channel: 'paper-inbox', last_run: null, papers: [PAPER] })
    render(<InboxTab onOpenClaude={() => {}} onRunJob={() => {}} />)
    expect(await screen.findByText('Agents in radiology')).toBeInTheDocument()
    expect(screen.getByText('Papers shared in #paper-inbox')).toBeInTheDocument()
    expect(screen.getByText('You wrote: look at this for Spyglass')).toBeInTheDocument()
    expect(screen.getByText('A benchmark of agentic triage.')).toBeInTheDocument()
    expect(screen.getByText('Read from the abstract only')).toBeInTheDocument()
    expect(screen.getByText('Shared 2 times')).toBeInTheDocument()
  })

  it('Process inbox opens a Claude session with the inbox prompt', async () => {
    stubInbox({ channel: 'paper-inbox', last_run: null, papers: [] })
    const onOpenClaude = vi.fn()
    const onRunJob = vi.fn()
    render(<InboxTab onOpenClaude={onOpenClaude} onRunJob={onRunJob} />)
    fireEvent.click(await screen.findByRole('button', { name: /process inbox/i }))
    // A job, not a conversation: it opens its own session, not the linked one.
    expect(onRunJob).toHaveBeenCalledWith(INBOX_PROMPT)
    expect(onOpenClaude).not.toHaveBeenCalled()
  })

  it('asks for a channel first', async () => {
    stubInbox({ channel: '', last_run: null, papers: [] })
    render(<InboxTab onOpenClaude={() => {}} onRunJob={() => {}} />)
    expect(await screen.findByText('Set the inbox channel in Settings first.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /process inbox/i })).toBeDisabled()
  })

  it('opens the debrief note and discusses a paper', async () => {
    stubInbox({ channel: 'c', last_run: null, papers: [PAPER] })
    const open = vi.spyOn(api, 'openInboxNote').mockResolvedValue({ opened: true })
    const onOpenClaude = vi.fn()
    render(<InboxTab onOpenClaude={onOpenClaude} onRunJob={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /open the debrief/i }))
    await waitFor(() => expect(open).toHaveBeenCalledWith(7))
    fireEvent.click(screen.getByRole('button', { name: /discuss in claude/i }))
    expect(onOpenClaude.mock.calls[0][0]).toEqual([7])
  })
})

describe('InboxTab run debriefs', () => {
  it('lists recent run debriefs and opens one', async () => {
    stubInbox({
      channel: 'c',
      last_run: null,
      papers: [],
      debriefs: [{ run_id: 4, papers: 3, debrief_path: '/v/d.md', started_at: new Date().toISOString() }],
    })
    const open = vi.spyOn(api, 'openRunDebrief').mockResolvedValue({ opened: true })
    render(<InboxTab onOpenClaude={() => {}} onRunJob={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /3 papers/i }))
    await waitFor(() => expect(open).toHaveBeenCalledWith(4))
  })
})

describe('InboxTab polling', () => {
  it('keeps looking for the run after Process inbox', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const getInbox = vi
      .spyOn(api, 'getInbox')
      .mockResolvedValue({ channel: 'c', last_run: null, papers: [] })
    render(<InboxTab onOpenClaude={() => {}} onRunJob={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /process inbox/i }))
    const before = getInbox.mock.calls.length
    await vi.advanceTimersByTimeAsync(15000)
    expect(getInbox.mock.calls.length).toBeGreaterThan(before)
    vi.useRealTimers()
  })
})

describe('runLine', () => {
  const base = { id: 1, papers: 3, error: null, started_at: new Date().toISOString(), finished_at: new Date().toISOString() }
  it('describes each state', () => {
    expect(runLine(null)).toBe('Not processed yet.')
    expect(runLine({ ...base, status: 'ok' })).toMatch(/: 3 papers\.$/)
    expect(runLine({ ...base, status: 'running' })).toMatch(/^Processing/)
    expect(runLine({ ...base, status: 'error', error: 'Slack is not connected' })).toMatch(
      /failed: Slack is not connected$/,
    )
  })
})
