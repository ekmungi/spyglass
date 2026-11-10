// The detailed note's actions and background-job status in the reader.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { JOBS_POLL_MS, useCardJobs } from '../../lib/useCardJobs'
import type { CardJobs, ClaudeJob } from '../../lib/types'
import { JobBar } from './JobBar'

const job = (over: Partial<ClaudeJob>): ClaudeJob => ({
  id: 1, kind: 'prepare-detail', card_id: 5, status: 'ok', note_path: null, message: null,
  progress: null, error: null, cost_usd: null, duration_ms: null, num_turns: null,
  created_at: null, started_at: null, finished_at: null, ...over,
})

function Harness({ onChanged, onRead = () => {}, onMove }: {
  onChanged?: () => void; onRead?: () => void; onMove?: (folder: string) => void
}) {
  const jobs = useCardJobs(5, onChanged)
  return <JobBar jobs={jobs} onRead={onRead} onMove={onMove} />
}

/** A fetch stub answering the jobs GET from a queue of states, and recording POSTs. */
function stub(states: CardJobs[], posts: { url: string; body: unknown }[] = [], refuse?: string) {
  let i = 0
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posts.push({ url, body: JSON.parse(String(init.body)) })
      if (refuse) return new Response(JSON.stringify({ detail: refuse }), { status: 409 })
      return new Response(JSON.stringify({ job: job({ status: 'queued' }), created: true, trashed: '.trash/x.md' }))
    }
    const state = states[Math.min(i, states.length - 1)]
    i += 1
    return new Response(JSON.stringify(state))
  })
}

const none: CardJobs = { jobs: [], note: { path: null, unfiled: false } }
const unfiled: CardJobs = { jobs: [job({ message: 'A note on optogenetics.' })],
  note: { path: '03 RESOURCES/Spyglass/Brief notes/2026-10-15/Primer.md', unfiled: true } }

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('JobBar', () => {
  it('offers Prepare detail when there is no note, and queues the job', async () => {
    const posts: { url: string; body: unknown }[] = []
    vi.stubGlobal('fetch', stub([none, { jobs: [job({ status: 'queued' })], note: none.note }], posts))
    render(<Harness />)
    fireEvent.click(await screen.findByRole('button', { name: /prepare detail/i }))
    await waitFor(() => expect(posts).toEqual([{ url: '/api/jobs', body: { kind: 'prepare-detail', card_id: 5 } }]))
    expect(await screen.findByRole('status')).toHaveTextContent('Preparing the detailed note: waiting')
    expect(screen.queryByRole('button', { name: /prepare detail/i })).not.toBeInTheDocument()
  })

  it('polls a running job and reloads the item when it ends', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const onChanged = vi.fn()
    vi.stubGlobal('fetch', stub([{ jobs: [job({ status: 'running' })], note: none.note }, unfiled]))
    render(<Harness onChanged={onChanged} />)
    expect(await screen.findByRole('status')).toHaveTextContent('Preparing the detailed note in the background')
    await act(async () => { await vi.advanceTimersByTimeAsync(JOBS_POLL_MS + 10) })
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('button', { name: /read detail/i })).toBeInTheDocument()
    expect(screen.getByText('Claude: A note on optogenetics.')).toBeInTheDocument()
  })

  it('reads, files and deletes an unfiled note', async () => {
    const posts: { url: string; body: unknown }[] = []
    const onRead = vi.fn()
    vi.stubGlobal('fetch', stub([unfiled], posts))
    render(<Harness onRead={onRead} />)
    fireEvent.click(await screen.findByRole('button', { name: /read detail/i }))
    expect(onRead).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /file it/i }))
    await waitFor(() => expect(posts[0]).toEqual({ url: '/api/jobs', body: { kind: 'file-note', card_id: 5 } }))
    fireEvent.click(screen.getByRole('button', { name: /delete note/i }))
    fireEvent.click(screen.getByRole('button', { name: /delete the note\?/i }))
    await waitFor(() => expect(posts[1].url).toBe('/api/cards/5/detail-note/delete'))
  })

  it('says where a note was filed and offers Move', async () => {
    const onMove = vi.fn()
    vi.stubGlobal('fetch', stub([{
      jobs: [job({ kind: 'file-note', message: 'Filed to 02 AREAS/Imaging: about microscopy.' })],
      note: { path: '02 AREAS/Imaging/Primer.md', unfiled: false },
    }]))
    render(<Harness onMove={onMove} />)
    expect(await screen.findByText('02 AREAS/Imaging')).toBeInTheDocument()
    expect(screen.getByText('Claude: Filed to 02 AREAS/Imaging: about microscopy.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /file it/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /delete note/i })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Move' }))
    expect(onMove).toHaveBeenCalledWith('02 AREAS/Imaging')
  })

  it('shows why a job failed and retries it', async () => {
    const posts: { url: string; body: unknown }[] = []
    vi.stubGlobal('fetch', stub([{
      jobs: [job({ kind: 'file-note', status: 'failed', error: 'Obsidian did not open within 90 seconds.' })],
      note: unfiled.note,
    }], posts))
    render(<Harness />)
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't file the note: Obsidian did not open within 90 seconds.")
    fireEvent.click(screen.getByRole('button', { name: /try again/i }))
    await waitFor(() => expect(posts[0].body).toEqual({ kind: 'file-note', card_id: 5 }))
  })

  it('offers Try again only when it can work', async () => {
    vi.stubGlobal('fetch', stub([{
      jobs: [job({ status: 'failed', error: 'Claude used all 40 turns without finishing.' })],
      note: unfiled.note,
    }]))
    render(<Harness />)
    expect(await screen.findByRole('alert')).toHaveTextContent('used all 40 turns')
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  it("shows the service's reason when it refuses", async () => {
    vi.stubGlobal('fetch', stub([none], [], 'Set the vault folder in Settings first.'))
    render(<Harness />)
    fireEvent.click(await screen.findByRole('button', { name: /prepare detail/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Set the vault folder in Settings first.')
  })
})
