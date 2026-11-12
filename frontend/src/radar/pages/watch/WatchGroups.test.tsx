// Tests for whole-group actions on the Watch page: pause, resume, rename, move and remove with undo.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import type { WatchRegister } from './api'
import { ToastViewport } from '../../ui'
import WatchPage from '../WatchPage'
import { clearLoadCache } from '../sources/useLoad'
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

/** The register after every Imaging AI name was muted. */
function pausedRegister(): WatchRegister {
  const next = register()
  next.categories[0] = {
    ...next.categories[0],
    paused: true,
    entities: next.categories[0].entities.map((e) => ({ ...e, status: 'muted' as const })),
  }
  return next
}

beforeEach(() => {
  clearLoadCache()
  vi.clearAllMocks()
  api.getWatch.mockResolvedValue(register())
  api.getTracks.mockResolvedValue([])
})

describe('group actions', () => {
  it('pauses a whole group in one choice and shows the answer without another request', async () => {
    api.patchWatchGroup.mockResolvedValue({ ...pausedRegister(), removed: [] })
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Pause this group')
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Imaging AI', action: 'pause' }))
    const group = await screen.findByRole('region', { name: 'Imaging AI' })
    expect(within(group).getByText('Paused')).toBeInTheDocument()
    expect(await screen.findByText('Paused Imaging AI')).toBeInTheDocument()
    expect(api.getWatch).toHaveBeenCalledTimes(1)
  })

  it('offers Resume instead of Pause on a paused group, and resumes with one click', async () => {
    api.patchWatchGroup.mockResolvedValue({ ...register(), removed: [] })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Resume Regulators' }))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenCalledWith({ category: 'Regulators', action: 'resume' }))
    fireEvent.click(screen.getByRole('button', { name: 'Actions for the group Regulators' }))
    expect(screen.queryByRole('menuitem', { name: 'Pause this group' })).not.toBeInTheDocument()
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
    expect(await screen.findByRole('region', { name: 'Scopes' })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(api.patchWatchGroup).toHaveBeenLastCalledWith({ category: 'Scopes', action: 'rename', to: 'Imaging AI' }))
    expect(await screen.findByRole('region', { name: 'Imaging AI' })).toBeInTheDocument()
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
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Imaging AI' })).not.toBeInTheDocument())
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
    expect(screen.queryByRole('region', { name: 'Imaging AI' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(api.restoreWatchGroup).toHaveBeenCalledWith(removed))
    expect(await screen.findByRole('region', { name: 'Imaging AI' })).toBeInTheDocument()
    expect(await screen.findByText('Restored 2 names')).toBeInTheDocument()
  })

  it('reports a failed pause in a toast', async () => {
    api.patchWatchGroup.mockRejectedValue(new ApiError('Spyglass is not reachable.', { status: 0, kind: 'network', path: '/watch/groups' }))
    renderPage()
    await chooseFromGroupMenu('Imaging AI', 'Pause this group')
    expect(await screen.findByText('Spyglass is not reachable.')).toBeInTheDocument()
    expect(entry({ id: 1, name: 'x' }).status).toBe('active')
  })
})
