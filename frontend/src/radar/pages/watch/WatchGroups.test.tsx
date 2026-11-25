// Tests for whole-group actions on the Watch page: pause, watch again, move up and down, rename, move and remove with undo.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import type { WatchRegister } from './api'
import { ToastViewport } from '../../ui'
import WatchPage from '../WatchPage'
import { clearLoadCache } from '../sources/useLoad'
import { clearToasts, entry, register } from './testFixtures'

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

function renderPage() {
  return render(
    <>
      <WatchPage />
      <ToastViewport />
    </>,
  )
}

/** Open a group's menu and choose an item. */
async function chooseFromGroupMenu(group: string, item: string) {
  fireEvent.click(await screen.findByRole('button', { name: `Actions for the group ${group}` }))
  fireEvent.click(screen.getByRole('menuitem', { name: item }))
}

/** The Undo button of the toast that says `message`. */
const undoOf = (message: string) => within(screen.getByText(message).closest('.r-toast') as HTMLElement).getByRole('button', { name: 'Undo' })

beforeEach(() => {
  clearLoadCache()
  clearToasts()
  vi.clearAllMocks()
  api.getWatch.mockResolvedValue(register())
  api.getTracks.mockResolvedValue([])
  api.changeEntry.mockResolvedValue({})
  // A pause or resume that names its names changes every one of them.
  api.patchWatchGroup.mockImplementation((body: { ids?: number[] }) => Promise.resolve({ ...register(), removed: [], changed: body.ids ?? [] }))
})

/** A register whose Imaging AI and Regulators groups both have watched names, so both are shown. */
function twoGroups(): WatchRegister {
  const next = register()
  next.categories[1] = { ...next.categories[1], paused: false, entities: next.categories[1].entities.map((e) => ({ ...e, status: 'active' as const })) }
  return next
}

/** The group names in the order the page shows them under Watching (the suggestion rows have headings too). */
const shownGroups = () =>
  within(screen.getByRole('region', { name: 'Watching' }))
    .getAllByRole('heading', { level: 3 })
    .map((node) => node.textContent)

describe('group actions', () => {
  it('pauses a group in place: the row and its chips stay and look paused, and Undo watches them again', async () => {
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Pause this group')
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Imaging AI', action: 'pause', ids: [1, 2] }))
    expect(await screen.findByText('Paused all 2 names in Imaging AI.')).toBeInTheDocument()
    // Nothing moves before the next visit: the row stays where it was, its chips grey, the Paused list as it was.
    const group = screen.getByRole('group', { name: 'Imaging AI' })
    expect(within(group).queryAllByRole('button', { pressed: true })).toHaveLength(0)
    expect(within(group).getAllByRole('button', { pressed: false }).map((node) => node.textContent)).toEqual(['Alpha Scopes', 'Zeta Vision'])
    expect(screen.getByText('Paused (1)')).toBeInTheDocument()
    expect(api.getWatch).toHaveBeenCalledTimes(1)

    fireEvent.click(undoOf('Paused all 2 names in Imaging AI.'))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenLastCalledWith({ category: 'Imaging AI', action: 'resume', ids: [1, 2] }))
    await waitFor(() => expect(within(group).getAllByRole('button', { pressed: true })).toHaveLength(2))
  })

  it('keeps a name paused before the group pause paused after its Undo, and leaves a name changed since alone', async () => {
    renderPage()
    const group = await screen.findByRole('group', { name: 'Imaging AI' })
    fireEvent.click(within(group).getByRole('button', { name: 'Alpha Scopes' }))
    await screen.findByText(/^Paused Alpha Scopes\./)
    fireEvent.click(screen.getByRole('button', { name: 'Actions for the group Imaging AI' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Pause this group' }))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Imaging AI', action: 'pause', ids: [2] }))
    await screen.findByText('Paused all 2 names in Imaging AI.')

    fireEvent.click(undoOf('Paused all 2 names in Imaging AI.'))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenLastCalledWith({ category: 'Imaging AI', action: 'resume', ids: [2] }))
    await waitFor(() => expect(within(group).getByRole('button', { name: 'Zeta Vision' })).toHaveAttribute('aria-pressed', 'true'))
    expect(within(group).getByRole('button', { name: 'Alpha Scopes' })).toHaveAttribute('aria-pressed', 'false')

    // A late Undo does nothing to a name the reader has switched since.
    fireEvent.click(screen.getByRole('button', { name: 'Actions for the group Imaging AI' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Pause this group' }))
    await screen.findByText('Paused all 2 names in Imaging AI.')
    fireEvent.click(within(group).getByRole('button', { name: 'Zeta Vision' }))
    await screen.findByText(/^Watching Zeta Vision again\./)
    const calls = api.patchWatchGroup.mock.calls.length
    fireEvent.click(undoOf('Paused all 2 names in Imaging AI.'))
    await waitFor(() => expect(within(group).getByRole('button', { name: 'Zeta Vision' })).toHaveAttribute('aria-pressed', 'true'))
    expect(api.patchWatchGroup).toHaveBeenCalledTimes(calls)
  })

  it('watches again, in place, only the names the row shows, and Undo pauses exactly those again', async () => {
    const withPaused = register()
    withPaused.categories[0].entities.push(entry({ id: 4, name: 'Beta Optics', status: 'muted' }))
    api.getWatch.mockResolvedValue(withPaused)
    renderPage()
    const group = await screen.findByRole('group', { name: 'Imaging AI' })
    fireEvent.click(within(group).getByRole('button', { name: 'Alpha Scopes' }))
    fireEvent.click(within(group).getByRole('button', { name: 'Zeta Vision' }))
    await waitFor(() => expect(within(group).queryAllByRole('button', { pressed: true })).toHaveLength(0))
    fireEvent.click(screen.getByRole('button', { name: 'Actions for the group Imaging AI' }))
    expect(screen.queryByRole('menuitem', { name: 'Pause this group' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Watch this group again' }))
    // Beta Optics was paused before this visit and waits in the Paused list; it is not resumed.
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Imaging AI', action: 'resume', ids: [1, 2] }))
    expect(await screen.findByText('Watching all 2 names in Imaging AI again.')).toBeInTheDocument()
    expect(within(group).getAllByRole('button', { pressed: true })).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Beta Optics, in Imaging AI' })).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(undoOf('Watching all 2 names in Imaging AI again.'))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenLastCalledWith({ category: 'Imaging AI', action: 'pause', ids: [1, 2] }))
    await waitFor(() => expect(within(group).queryAllByRole('button', { pressed: true })).toHaveLength(0))
  })

  it('moves a group down the page, and cannot move the first group up', async () => {
    api.getWatch.mockResolvedValue(twoGroups())
    const swapped = twoGroups()
    swapped.categories = [swapped.categories[1], swapped.categories[0]]
    api.patchWatchGroup.mockResolvedValue({ ...swapped, removed: [] })
    renderPage()
    await screen.findByRole('group', { name: 'Regulators' })
    expect(shownGroups()).toEqual(['Imaging AI', 'Regulators'])
    fireEvent.click(screen.getByRole('button', { name: 'Actions for the group Imaging AI' }))
    expect(screen.getByRole('menuitem', { name: 'Move up' })).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(screen.getByRole('menuitem', { name: 'Move down' }))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Imaging AI', action: 'down' }))
    await waitFor(() => expect(shownGroups()).toEqual(['Regulators', 'Imaging AI']))
    expect(api.patchWatchGroup).toHaveBeenCalledTimes(1)
  })

  it('moves a group past one that is hidden because all its names are paused', async () => {
    const withHidden = twoGroups()
    withHidden.categories = [
      withHidden.categories[0],
      { name: 'Dormant', paused: true, entities: [entry({ id: 7, name: 'Quiet Co', category: 'Dormant', status: 'muted' })] },
      withHidden.categories[1],
    ]
    api.getWatch.mockResolvedValue(withHidden)
    api.patchWatchGroup.mockResolvedValue({ ...twoGroups(), removed: [] })
    renderPage()
    await chooseFromGroupMenu('Regulators', 'Move up')
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledTimes(2))
    expect(api.patchWatchGroup).toHaveBeenNthCalledWith(1, { category: 'Regulators', action: 'up' })
    expect(api.patchWatchGroup).toHaveBeenNthCalledWith(2, { category: 'Regulators', action: 'up' })
  })

  it('shows the order the service reached when a later step of a move fails, so the next move goes one place', async () => {
    const shown = twoGroups()
    const dormant = { name: 'Dormant', paused: true, entities: [entry({ id: 7, name: 'Quiet Co', category: 'Dormant', status: 'muted' })] }
    const [imaging, regulators] = shown.categories
    api.getWatch.mockResolvedValue({ ...shown, categories: [imaging, dormant, regulators] })
    api.patchWatchGroup
      .mockResolvedValueOnce({ ...shown, categories: [dormant, imaging, regulators], removed: [] })
      .mockRejectedValueOnce(new ApiError('Spyglass is not reachable.', { status: 0, kind: 'network', path: '/watch/groups' }))
      .mockResolvedValue({ ...shown, categories: [dormant, regulators, imaging], removed: [] })
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Move down')
    expect(await screen.findByText('Spyglass is not reachable.')).toBeInTheDocument()
    expect(api.patchWatchGroup).toHaveBeenCalledTimes(2)

    // The first step passed Dormant, so one more step now reaches Regulators.
    await chooseFromGroupMenu('Imaging AI', 'Move down')
    expect(await screen.findByText('Moved Imaging AI down')).toBeInTheDocument()
    expect(api.patchWatchGroup).toHaveBeenCalledTimes(3)
    expect(shownGroups()).toEqual(['Regulators', 'Imaging AI'])
  })

  it('renames a group, and Undo renames it back', async () => {
    const renamed = register()
    renamed.categories[0] = { ...renamed.categories[0], name: 'Scopes' }
    api.patchWatchGroup.mockResolvedValueOnce({ ...renamed, removed: [] }).mockResolvedValueOnce({ ...register(), removed: [] })
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Rename group…')
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Group name'), { target: { value: 'Scopes' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Rename' }))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Imaging AI', action: 'rename', to: 'Scopes' }))
    expect(await screen.findByRole('group', { name: 'Scopes' })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenLastCalledWith({ category: 'Scopes', action: 'rename', to: 'Imaging AI' }))
    expect(await screen.findByRole('group', { name: 'Imaging AI' })).toBeInTheDocument()
  })

  it('refuses an empty or too long group name before asking the service', async () => {
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Rename group…')
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Group name'), { target: { value: '   ' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Rename' }))
    expect(await within(dialog).findByText('Give the group a name.')).toBeInTheDocument()
    expect(api.patchWatchGroup).not.toHaveBeenCalled()
  })

  it('shows the service refusal inside the rename dialog', async () => {
    api.patchWatchGroup.mockRejectedValue(new ApiError('A group name must be a single line of text.', { status: 422, kind: 'http', path: '/watch/groups' }))
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Rename group…')
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Group name'), { target: { value: 'Scopes' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Rename' }))
    expect(await within(dialog).findByText('A group name must be a single line of text.')).toBeInTheDocument()
  })

  it('moves every name to another group chosen from the list', async () => {
    const moved = register()
    moved.categories = [{ name: 'Regulators', week_count: 0, paused: false, entities: [...moved.categories[1].entities, ...moved.categories[0].entities] }]
    api.patchWatchGroup.mockResolvedValue({ ...moved, removed: [] })
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Move all to another group…')
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByLabelText('Move to')).toHaveValue('Regulators')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Imaging AI', action: 'move', to: 'Regulators' }))
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Imaging AI' })).not.toBeInTheDocument())
  })

  it('moves to a new group when a new name is typed', async () => {
    api.patchWatchGroup.mockResolvedValue({ ...register(), removed: [] })
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Move all to another group…')
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Move to'), { target: { value: '__new__' } })
    fireEvent.change(within(dialog).getByLabelText('New group name'), { target: { value: 'Capsule makers' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Imaging AI', action: 'move', to: 'Capsule makers' }))
  })

  it('asks before removing a group, naming how many names go, and Undo restores them', async () => {
    const removed = register().categories[0].entities.map((e) => ({ ...e, links: [] }))
    const after = register()
    after.categories = [after.categories[1]]
    api.patchWatchGroup.mockResolvedValue({ ...after, removed })
    api.restoreWatchGroup.mockResolvedValue({ ...register(), restored: 2 })
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Remove this group…')
    const dialog = screen.getByRole('dialog', { name: 'Remove Imaging AI?' })
    expect(within(dialog).getByText(/all 2 names in this group/)).toBeInTheDocument()
    expect(api.patchWatchGroup).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove group' }))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Imaging AI', action: 'remove' }))
    expect(await screen.findByText('Removed Imaging AI (2 names)')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Imaging AI' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(api.restoreWatchGroup).toHaveBeenCalledWith(removed))
    expect(await screen.findByRole('group', { name: 'Imaging AI' })).toBeInTheDocument()
    expect(await screen.findByText('Restored 2 names')).toBeInTheDocument()
  })

  it('puts the looks back and reports a failed group pause in a toast', async () => {
    api.patchWatchGroup.mockRejectedValue(new ApiError('Spyglass is not reachable.', { status: 0, kind: 'network', path: '/watch/groups' }))
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Pause this group')
    expect(await screen.findByText('Spyglass is not reachable.')).toBeInTheDocument()
    const group = screen.getByRole('group', { name: 'Imaging AI' })
    expect(within(group).getAllByRole('button', { pressed: true })).toHaveLength(2)
    expect(screen.queryByText(/^Paused all/)).not.toBeInTheDocument()
  })
})
