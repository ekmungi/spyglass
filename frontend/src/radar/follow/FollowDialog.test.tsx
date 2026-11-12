// Tests for the follow dialog: loading, the checklist, following with one failure, already-followed
// lines, the basic-suggestions note, the address source, retry and the similar-items list.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/errors'
import type { RadarItem, TrackSuggestResponse, TrackSuggestion } from '../api/types'
import { ToastViewport } from '../ui'
import { FollowDialog, type FollowSource } from './FollowDialog'

const api = vi.hoisted(() => ({ suggestTracksForItem: vi.fn(), suggestTracksForUrl: vi.fn(), createTrack: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

function suggestion(over: Partial<TrackSuggestion>): TrackSuggestion {
  return { label: 'Surgical robotics', query: 'surgical robotics', kind: 'topic', section: 'health', section_label: 'Healthcare AI & medtech', why: 'The field of the article.', already_followed: false, ...over }
}

function item(id: number, headline: string): RadarItem {
  return { id, title: headline, headline, origin: 'Medtech Dispatch', published_at: null, fetched_at: '2026-11-12T08:00:00Z' } as RadarItem
}

const REPLY: TrackSuggestResponse = {
  mode: 'ai',
  suggestions: [
    suggestion({ label: 'Virtuoso Surgical', query: '"Virtuoso Surgical"', kind: 'organisation', why: 'The company in the headline.' }),
    suggestion({ label: 'En bloc bladder tumor resection', query: 'en bloc bladder tumor resection', why: 'The procedure the robot performs.' }),
    suggestion({ label: 'Intuitive Surgical', query: '"Intuitive Surgical"', kind: 'organisation', why: 'The market leader.', already_followed: true }),
  ],
  similar: [item(201, 'Another robot is cleared'), item(202, 'Endoluminal surgery grows')],
}

function open(source: FollowSource = { kind: 'item', id: 42 }, onClose = vi.fn()) {
  render(
    <>
      <FollowDialog open source={source} onClose={onClose} />
      <ToastViewport />
    </>,
  )
  return onClose
}

beforeEach(() => {
  vi.clearAllMocks()
  api.suggestTracksForItem.mockResolvedValue(REPLY)
  api.suggestTracksForUrl.mockResolvedValue({ ...REPLY, item: item(300, 'The added page') })
  api.createTrack.mockImplementation(async (body: { label: string }) => ({ id: 1, ...body, new_items: 3 }))
})

describe('FollowDialog', () => {
  it('shows an honest waiting line while it reads, then the checklist', async () => {
    let finish: (value: TrackSuggestResponse) => void = () => undefined
    api.suggestTracksForItem.mockReturnValue(new Promise<TrackSuggestResponse>((resolve) => (finish = resolve)))
    open()
    const dialog = screen.getByRole('dialog', { name: 'Follow more like this' })
    expect(within(dialog).getByRole('status')).toHaveTextContent('Reading the article to suggest what to follow…')
    finish(REPLY)
    expect(await within(dialog).findByRole('checkbox', { name: 'Virtuoso Surgical' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('status')).not.toBeInTheDocument()
  })

  it('ticks only the single most specific suggestion and disables what is already followed', async () => {
    open()
    const specific = await screen.findByRole('checkbox', { name: 'En bloc bladder tumor resection' })
    expect(specific).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Virtuoso Surgical' })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Intuitive Surgical' })).toBeDisabled()
    expect(screen.getByText('Already following')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Virtuoso Surgical' })).toHaveAccessibleDescription('The company in the headline.')
  })

  it('follows the ticked lines with the item id, then closes with a summary toast', async () => {
    const onClose = open()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Virtuoso Surgical' }))
    fireEvent.click(screen.getByRole('button', { name: 'Follow selected' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(api.createTrack).toHaveBeenCalledTimes(2)
    expect(api.createTrack).toHaveBeenCalledWith({ label: 'Virtuoso Surgical', query: '"Virtuoso Surgical"', section: 'health', kind: 'organisation', from_item_id: 42 })
    expect(await screen.findByText('Following 2 topics · 6 new items found; they will be judged in the next collection')).toBeInTheDocument()
  })

  it('reports one failure on its own line, keeps it ticked for a retry and summarises on close', async () => {
    api.createTrack.mockImplementation(async (body: { label: string }) => {
      if (body.label === 'Virtuoso Surgical') throw new ApiError('The first search could not be run.', { status: 422, kind: 'http', path: '/tracks' })
      return { id: 1, ...body, new_items: 4 }
    })
    const onClose = open()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Virtuoso Surgical' }))
    fireEvent.click(screen.getByRole('button', { name: 'Follow selected' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The first search could not be run.')
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByText('Following')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'En bloc bladder tumor resection' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: 'Virtuoso Surgical' })).toBeChecked()
    fireEvent.click(within(screen.getByRole('dialog')).getAllByRole('button', { name: 'Close' }).at(-1) as HTMLElement)
    expect(onClose).toHaveBeenCalled()
    expect(await screen.findByText('Following 1 topic · 4 new items found; they will be judged in the next collection')).toBeInTheDocument()
  })

  it('treats a 409 as already following, not as a failure', async () => {
    api.createTrack.mockRejectedValue(new ApiError('You already follow this.', { status: 409, kind: 'http', path: '/tracks' }))
    const onClose = open()
    await screen.findByRole('checkbox', { name: 'En bloc bladder tumor resection' })
    fireEvent.click(screen.getByRole('button', { name: 'Follow selected' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says when the suggestions are basic and when there is nothing obvious, and still lists similar items', async () => {
    api.suggestTracksForItem.mockResolvedValue({ mode: 'basic', suggestions: [], similar: REPLY.similar })
    open()
    expect(await screen.findByText('Basic suggestions; the AI service was not available.')).toBeInTheDocument()
    expect(screen.getByText('Nothing obvious to follow in this article.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Another robot is cleared' })).toHaveAttribute('href', '#/item/201')
    expect(screen.getByRole('button', { name: 'Follow selected' })).toBeDisabled()
  })

  it('lists at most eight similar items under "Similar in your feed"', async () => {
    api.suggestTracksForItem.mockResolvedValue({ ...REPLY, similar: Array.from({ length: 11 }, (_, index) => item(400 + index, `Similar story ${index}`)) })
    open()
    const heading = await screen.findByRole('heading', { name: 'Similar in your feed' })
    const list = heading.closest('section') as HTMLElement
    expect(within(list).getAllByRole('link')).toHaveLength(8)
  })

  it('reads an address, and links the new topics to the item the address became', async () => {
    open({ kind: 'url', url: 'https://example.org/page' })
    expect(within(screen.getByRole('dialog')).getByRole('status')).toHaveTextContent('Reading the link')
    await screen.findByRole('checkbox', { name: 'Virtuoso Surgical' })
    expect(api.suggestTracksForUrl).toHaveBeenCalledWith('https://example.org/page', expect.anything())
    fireEvent.click(screen.getByRole('button', { name: 'Follow selected' }))
    await waitFor(() => expect(api.createTrack).toHaveBeenCalledWith(expect.objectContaining({ from_item_id: 300 })))
  })

  it('shows a refused address in words and retries', async () => {
    api.suggestTracksForUrl.mockRejectedValueOnce(new ApiError('That address points to a private network.', { status: 422, kind: 'http', path: '/track/suggest' }))
    open({ kind: 'url', url: 'http://10.0.0.1/x' })
    expect(await screen.findByRole('alert')).toHaveTextContent('private network')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('checkbox', { name: 'Virtuoso Surgical' })).toBeInTheDocument()
  })
})
