// Tests for "Review with AI": the waiting line, the checklists (nothing pre-ticked), applying exactly what was ticked, and failures.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import type { WatchReview } from '../../api/types'
import { ToastViewport } from '../../ui'
import WatchPage from '../WatchPage'
import { clearLoadCache } from '../sources/useLoad'
import { describeApplied } from './reviewText'
import { entry, register } from './testFixtures'

const api = vi.hoisted(() => ({
  getWatch: vi.fn(),
  deleteWatch: vi.fn(),
  discoverTopic: vi.fn(),
  addEntry: vi.fn(),
  changeEntry: vi.fn(),
  getTracks: vi.fn(),
  createTrack: vi.fn(),
  patchTrack: vi.fn(),
  deleteTrack: vi.fn(),
  patchWatchGroup: vi.fn(),
  restoreWatchGroup: vi.fn(),
  reviewWatch: vi.fn(),
  applyWatchReview: vi.fn(),
}))
vi.mock('./api', () => api)

function review(over: Partial<WatchReview> = {}): WatchReview {
  return {
    mode: 'ai',
    summary: 'One name has gone quiet and one company is missing.',
    pause: [{ id: 1, name: 'Alpha Scopes', category: 'Imaging AI', reason: 'Nothing new for six weeks.' }],
    remove: [{ id: 2, name: 'Zeta Vision', category: 'Imaging AI', reason: 'No longer fits your topics.' }],
    add: [{ name: 'Newco', kind: 'company', category: 'Imaging AI', why: 'Named in five relevant items.', query: '"Newco"' }],
    regroup: [{ id: 3, name: 'FDA', from: 'Regulators', to: 'Agencies', reason: 'A shorter name.' }],
    merge_groups: [{ from: 'Regulators', to: 'Agencies', reason: 'Same ground.', count: 1 }],
    ...over,
  }
}

function renderPage() {
  return render(
    <>
      <WatchPage />
      <ToastViewport />
    </>,
  )
}

async function openReview() {
  fireEvent.click(await screen.findByRole('button', { name: 'Review with AI' }))
  return screen.getByRole('dialog', { name: 'Review with AI' })
}

beforeEach(() => {
  clearLoadCache()
  vi.clearAllMocks()
  api.getWatch.mockResolvedValue(register())
  api.getTracks.mockResolvedValue([])
})

describe('Review with AI', () => {
  it('says honestly that it can take a minute, then shows the summary and every proposal unticked', async () => {
    let finish: (value: WatchReview) => void = () => {}
    api.reviewWatch.mockReturnValue(new Promise<WatchReview>((resolve) => (finish = resolve)))
    renderPage()
    const panel = await openReview()
    expect(within(panel).getByText(/can take up to a minute/)).toBeInTheDocument()
    finish(review())
    expect(await within(panel).findByText('One name has gone quiet and one company is missing.')).toBeInTheDocument()
    for (const legend of ['Pause', 'Remove', 'Add', 'Move to another group', 'Merge groups']) {
      expect(within(panel).getByRole('group', { name: legend })).toBeInTheDocument()
    }
    expect(within(panel).getByText('Nothing new for six weeks.')).toBeInTheDocument()
    expect(within(panel).getAllByRole('checkbox')).toHaveLength(5)
    within(panel).getAllByRole('checkbox').forEach((box) => expect(box).not.toBeChecked())
    expect(within(panel).getByRole('button', { name: 'Apply selected' })).toBeDisabled()
    expect(api.applyWatchReview).not.toHaveBeenCalled()
  })

  it('applies exactly what was ticked, then shows what changed with Undo for removals', async () => {
    api.reviewWatch.mockResolvedValue(review())
    const removed = [{ ...entry({ id: 2, name: 'Zeta Vision' }), links: [] }]
    const after = register()
    api.applyWatchReview.mockResolvedValue({ ...after, applied: { paused: 1, removed: 1, added: 0, regrouped: 0, merged: 0 }, removed })
    api.restoreWatchGroup.mockResolvedValue({ ...register(), restored: 1 })
    renderPage()
    const panel = await openReview()
    fireEvent.click(await within(panel).findByLabelText(/Alpha Scopes/))
    fireEvent.click(within(panel).getByLabelText(/Zeta Vision/))
    fireEvent.click(within(panel).getByRole('button', { name: 'Apply selected' }))
    await waitFor(() =>
      expect(api.applyWatchReview).toHaveBeenCalledWith({ pause: [1], remove: [2], add: [], regroup: [], merge_groups: [] }),
    )
    expect(await screen.findByText('Paused 1, removed 1')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Undo removal' }))
    await waitFor(() => expect(api.restoreWatchGroup).toHaveBeenCalledWith(removed))
  })

  it('sends additions, moves and merges when those are ticked', async () => {
    api.reviewWatch.mockResolvedValue(review())
    api.applyWatchReview.mockResolvedValue({ ...register(), applied: { paused: 0, removed: 0, added: 1, regrouped: 1, merged: 1 }, removed: [] })
    renderPage()
    const panel = await openReview()
    fireEvent.click(await within(panel).findByLabelText(/Newco/))
    fireEvent.click(within(panel).getByLabelText(/FDA to Agencies/))
    fireEvent.click(within(panel).getByLabelText(/Regulators into Agencies/))
    fireEvent.click(within(panel).getByRole('button', { name: 'Apply selected' }))
    await waitFor(() =>
      expect(api.applyWatchReview).toHaveBeenCalledWith({
        pause: [],
        remove: [],
        add: [{ name: 'Newco', kind: 'company', category: 'Imaging AI', why: 'Named in five relevant items.', query: '"Newco"' }],
        regroup: [{ id: 3, to: 'Agencies' }],
        merge_groups: [{ from: 'Regulators', to: 'Agencies' }],
      }),
    )
    expect(screen.queryByRole('button', { name: 'Undo removal' })).not.toBeInTheDocument()
  })

  it('says when the review is the basic one and when nothing needs changing', async () => {
    api.reviewWatch.mockResolvedValue(
      review({ mode: 'basic', note: 'No AI model is set up, so this is the basic review.', summary: 'Nothing stands out; your list looks current.', pause: [], remove: [], add: [], regroup: [], merge_groups: [] }),
    )
    renderPage()
    const panel = await openReview()
    expect(await within(panel).findByText('No AI model is set up, so this is the basic review.')).toBeInTheDocument()
    expect(within(panel).getByText('There is nothing to change right now.')).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Apply selected' })).not.toBeInTheDocument()
  })

  it('offers a retry when the review cannot run', async () => {
    api.reviewWatch.mockRejectedValueOnce(new ApiError('The review could not be completed; try again later', { status: 502, kind: 'http', path: '/watch/review' }))
    api.reviewWatch.mockResolvedValueOnce(review())
    renderPage()
    const panel = await openReview()
    expect(await within(panel).findByRole('alert')).toHaveTextContent('The review could not be completed')
    fireEvent.click(within(panel).getByRole('button', { name: 'Try again' }))
    expect(await within(panel).findByText('One name has gone quiet and one company is missing.')).toBeInTheDocument()
    expect(api.reviewWatch).toHaveBeenCalledTimes(2)
  })

  it('keeps the panel open and shows the refusal when applying fails', async () => {
    api.reviewWatch.mockResolvedValue(review())
    api.applyWatchReview.mockRejectedValue(new ApiError('A group name must be a single line of text.', { status: 422, kind: 'http', path: '/watch/review/apply' }))
    renderPage()
    const panel = await openReview()
    fireEvent.click(await within(panel).findByLabelText(/Alpha Scopes/))
    fireEvent.click(within(panel).getByRole('button', { name: 'Apply selected' }))
    expect(await within(panel).findByText('A group name must be a single line of text.')).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Review with AI' })).toBeInTheDocument()
  })
})

describe('describeApplied', () => {
  it('lists only what changed, and says so when nothing did', () => {
    expect(describeApplied({ paused: 2, removed: 0, added: 1, regrouped: 0, merged: 3 })).toBe('Paused 2, added 1, merged 3 into other groups')
    expect(describeApplied({ paused: 0, removed: 0, added: 0, regrouped: 0, merged: 0 })).toBe('Nothing changed')
  })
})
