// Tests for "Topics you follow" on the Watch page: rows, the Feed link, pause, stop with undo, edit and the empty state.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Track } from '../../api/types'
import { ToastViewport } from '../../ui'
import { clearLoadCache } from '../sources/useLoad'
import { TopicsSection } from './TopicsSection'
import { checkedLine } from './checkedLine'

const api = vi.hoisted(() => ({
  getTracks: vi.fn(),
  createTrack: vi.fn(),
  patchTrack: vi.fn(),
  deleteTrack: vi.fn(),
}))
vi.mock('./api', () => api)

function track(over: Partial<Track> = {}): Track {
  return {
    id: 7,
    label: 'Polyp detection',
    query: 'polyp detection AI',
    section: 'health',
    section_label: 'Healthcare AI & medtech',
    kind: 'topic',
    active: true,
    created_at: '2026-11-01T08:00:00Z',
    from_item_id: 42,
    last_run_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
    last_new: 2,
    recent: [
      {
        id: 55,
        title: 'Clearance for a detector',
        headline: 'Clearance for a detector',
        published_at: new Date().toISOString(),
        fetched_at: new Date().toISOString(),
      } as never,
    ],
    ...over,
  }
}

function renderSection() {
  return render(
    <>
      <TopicsSection />
      <ToastViewport />
    </>,
  )
}

beforeEach(() => {
  clearLoadCache()
  vi.clearAllMocks()
  api.getTracks.mockResolvedValue([track()])
  api.patchTrack.mockResolvedValue(track())
  api.deleteTrack.mockResolvedValue({ deleted: 7 })
  api.createTrack.mockResolvedValue({ ...track(), new_items: 1 })
})

describe('TopicsSection', () => {
  it('shows each topic with its section, last check, recent items and a Feed link', async () => {
    renderSection()
    const link = await screen.findByRole('link', { name: 'Polyp detection' })
    expect(link).toHaveAttribute('href', '#/feed?q=Polyp+detection')
    expect(screen.getByText('Healthcare AI & medtech')).toBeInTheDocument()
    expect(screen.getByText(/Last checked 3 h ago · 2 new/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Clearance for a detector' })).toHaveAttribute('href', '#/item/55')
  })

  it('explains how to follow something when there are no topics', async () => {
    api.getTracks.mockResolvedValue([])
    renderSection()
    expect(await screen.findByText('You are not following any topics yet')).toBeInTheDocument()
    expect(screen.getByText(/Use Add, at the top of the page, to follow a topic/)).toBeInTheDocument()
  })

  it('pauses a topic and offers Resume afterwards', async () => {
    renderSection()
    fireEvent.click(await screen.findByRole('button', { name: 'Actions for Polyp detection' }))
    api.getTracks.mockResolvedValue([track({ active: false })])
    fireEvent.click(screen.getByRole('menuitem', { name: /Pause/ }))
    await waitFor(() => expect(api.patchTrack).toHaveBeenCalledWith(7, { active: false }))
    expect(await screen.findByText('Paused')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Polyp detection' }))
    expect(screen.getByRole('menuitem', { name: 'Resume' })).toBeInTheDocument()
  })

  it('stops following and undoes it by creating the topic again with the same settings', async () => {
    renderSection()
    fireEvent.click(await screen.findByRole('button', { name: 'Actions for Polyp detection' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Stop following' }))
    await waitFor(() => expect(api.deleteTrack).toHaveBeenCalledWith(7))
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }))
    await waitFor(() =>
      expect(api.createTrack).toHaveBeenCalledWith({ label: 'Polyp detection', query: 'polyp detection AI', section: 'health', kind: 'topic', from_item_id: 42 }),
    )
  })

  it('edits the name, query and section', async () => {
    renderSection()
    fireEvent.click(await screen.findByRole('button', { name: 'Actions for Polyp detection' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Colonoscopy AI' } })
    fireEvent.change(within(dialog).getByLabelText('Search query'), { target: { value: 'colonoscopy AI' } })
    fireEvent.change(within(dialog).getByLabelText('Section'), { target: { value: 'models' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(api.patchTrack).toHaveBeenCalledWith(7, { label: 'Colonoscopy AI', query: 'colonoscopy AI', section: 'models' }))
  })

  it('refuses an edit with an empty query', async () => {
    renderSection()
    fireEvent.click(await screen.findByRole('button', { name: 'Actions for Polyp detection' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Search query'), { target: { value: ' ' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('needs a name and a search query')
    expect(api.patchTrack).not.toHaveBeenCalled()
  })
})

describe('checkedLine', () => {
  it('says "Not checked yet" before the first search and "nothing new" for zero finds', () => {
    expect(checkedLine({ last_run_at: null, last_new: 0 })).toBe('Not checked yet')
    expect(checkedLine({ last_run_at: new Date().toISOString(), last_new: 0 })).toBe('Last checked just now · nothing new')
  })
})
