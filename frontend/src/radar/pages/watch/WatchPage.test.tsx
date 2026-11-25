// Tests for the Watch page: layout, the watched names as chips and the Paused list, the chip menu, the
// Add dialog's three paths, suggestions and errors.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import { ToastViewport } from '../../ui'
import WatchPage from '../WatchPage'
import { clearLoadCache } from '../sources/useLoad'
import type { DiscoverResult } from './api'
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

/** Open the Add dialog and choose one of its three paths. */
async function openAdd(path: string | RegExp) {
  fireEvent.click(await screen.findByRole('button', { name: 'Add' }))
  const dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: path }))
  return screen.getByRole('dialog')
}

beforeEach(() => {
  clearLoadCache()
  clearToasts()
  vi.clearAllMocks()
  api.getWatch.mockResolvedValue(register())
  api.changeEntry.mockResolvedValue({})
  api.deleteWatch.mockResolvedValue({})
  api.addEntry.mockResolvedValue({})
  api.createTrack.mockResolvedValue({})
  api.getTracks.mockResolvedValue([])
})

describe('WatchPage layout', () => {
  it('starts with the title, one explanatory sentence and the Add and Review buttons', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { level: 1, name: 'Watch' })).toBeInTheDocument()
    expect(
      screen.getByText("Spyglass searches the news for each of these once a day. What it finds goes into your Feed, and the important ones appear in your brief under 'On your watch list'."),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Review with AI' })).toBeInTheDocument()
    // The old bottom button and the separate discovery bar are gone.
    expect(screen.queryByRole('button', { name: 'Add a name' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Find who matters for a topic')).not.toBeInTheDocument()
  })

  it('shows suggestions first, then Watching: each group a heading followed by its names as chips', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Suggested' })).toBeInTheDocument()
    expect(screen.getByText('Gamma Labs')).toBeInTheDocument()
    const headings = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent)
    expect(headings.slice(0, 4)).toEqual(['Topics you follow', 'You are not following any topics yet', 'Suggested', 'Watching'])
    expect(screen.getByText('2 watched · 1 group')).toBeInTheDocument()

    const group = screen.getByRole('group', { name: 'Imaging AI' })
    expect(within(group).getByRole('heading', { level: 3, name: 'Imaging AI' })).toBeInTheDocument()
    // The names keep the server's order, so nothing is re-sorted while the page is open.
    const chips = within(group).getAllByRole('button', { pressed: true }).map((node) => node.textContent)
    expect(chips).toEqual(['Alpha Scopes', 'Zeta Vision'])
  })

  it('says how many items each group brought into the Feed this week', async () => {
    renderPage()
    const group = await screen.findByRole('group', { name: 'Imaging AI' })
    expect(within(group).getByRole('link', { name: '3 items this week' })).toBeInTheDocument()
  })

  it('leaves out a group whose names are all paused, and lists them under a collapsed "Paused (1)" with their group', async () => {
    renderPage()
    const list = (await screen.findByText('Paused (1)')).closest('details') as HTMLElement
    expect(list).not.toHaveAttribute('open')
    expect(screen.queryByRole('group', { name: 'Regulators' })).not.toBeInTheDocument()
    expect(within(list).getByRole('button', { name: 'FDA, in Regulators' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByText(/^Muted \(/)).not.toBeInTheDocument()
  })

  it('accepts a suggestion by making it active and reloads the list', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Accept Gamma Labs' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenCalledWith(9, { status: 'active' }))
    await waitFor(() => expect(api.getWatch).toHaveBeenCalledTimes(2))
  })

  it('dismisses a suggestion by muting it', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss Gamma Labs' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenCalledWith(9, { status: 'muted' }))
  })

  it('asks before removing a name', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'More actions for Alpha Scopes' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Remove…' }))
    expect(api.deleteWatch).not.toHaveBeenCalled()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(api.deleteWatch).toHaveBeenCalledWith(1))
  })

  it('offers a retry when the list cannot be loaded', async () => {
    api.getWatch.mockRejectedValueOnce(new ApiError('Spyglass is not reachable. Check that the service is running, then try again.', { status: 0, kind: 'network', path: '/watch' }))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('Spyglass is not reachable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Gamma Labs')).toBeInTheDocument()
  })

  it('shows an empty state whose button opens the Add dialog', async () => {
    api.getWatch.mockResolvedValue({ categories: [], suggested: [], rejected: [], sections: [] })
    renderPage()
    expect(await screen.findByText('Nothing on your watch list yet')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add something to watch' }))
    expect(within(screen.getByRole('dialog')).getByRole('button', { name: /Find who matters for a topic/ })).toBeInTheDocument()
  })
})

/** Open a chip's menu and choose an item. */
async function chooseFromChipMenu(name: string, item: string) {
  fireEvent.click(await screen.findByRole('button', { name: `More actions for ${name}` }))
  fireEvent.click(screen.getByRole('menuitem', { name: item }))
}

describe('Watching chips', () => {
  it('pauses a name with one click: the chip stays in its group, unpressed, and the toast offers Undo', async () => {
    renderPage()
    const group = await screen.findByRole('group', { name: 'Imaging AI' })
    const chip = within(group).getByRole('button', { name: 'Zeta Vision' })
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(chip)
    await waitFor(() => expect(api.changeEntry).toHaveBeenCalledWith(2, { status: 'muted' }))
    expect(within(group).getByRole('button', { name: 'Zeta Vision' })).toHaveAttribute('aria-pressed', 'false')
    expect(await screen.findByText('Paused Zeta Vision. Spyglass stops searching for it. Nothing is deleted.')).toBeInTheDocument()
    // Nothing reloads, so nothing moves: the Paused list is still the one from the load.
    expect(api.getWatch).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Paused (1)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenLastCalledWith(2, { status: 'active' }))
    await waitFor(() => expect(within(group).getByRole('button', { name: 'Zeta Vision' })).toHaveAttribute('aria-pressed', 'true'))
  })

  it('watches a name again with a second click, in place', async () => {
    renderPage()
    const group = await screen.findByRole('group', { name: 'Imaging AI' })
    fireEvent.click(within(group).getByRole('button', { name: 'Alpha Scopes' }))
    await screen.findByText(/^Paused Alpha Scopes\./)
    fireEvent.click(within(group).getByRole('button', { name: 'Alpha Scopes' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenLastCalledWith(1, { status: 'active' }))
    expect(await screen.findByText('Watching Alpha Scopes again. Spyglass searches for it from the next run.')).toBeInTheDocument()
    expect(within(group).getByRole('button', { name: 'Alpha Scopes' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('watches a paused name again from the Paused list, where it stays', async () => {
    renderPage()
    const list = (await screen.findByText('Paused (1)')).closest('details') as HTMLElement
    fireEvent.click(within(list).getByRole('button', { name: 'FDA, in Regulators' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenCalledWith(3, { status: 'active' }))
    expect(within(list).getByRole('button', { name: 'FDA, in Regulators' })).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByText('Watching FDA again. Spyglass searches for it from the next run.')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Regulators' })).not.toBeInTheDocument()
    expect(api.getWatch).toHaveBeenCalledTimes(1)
  })

  it('shows a name paused on this visit in the Paused list as soon as the page is opened again', async () => {
    const view = renderPage()
    const group = await screen.findByRole('group', { name: 'Imaging AI' })
    fireEvent.click(within(group).getByRole('button', { name: 'Zeta Vision' }))
    await screen.findByText(/^Paused Zeta Vision\./)
    view.unmount()
    // The fresh answer has not arrived yet, so the page shows the one it remembered.
    api.getWatch.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(await screen.findByText('Paused (2)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zeta Vision, in Imaging AI' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('puts the chip back and says why when the change fails', async () => {
    api.changeEntry.mockRejectedValue(new ApiError('Spyglass is not reachable.', { status: 0, kind: 'network', path: '/watch/1' }))
    renderPage()
    const group = await screen.findByRole('group', { name: 'Imaging AI' })
    fireEvent.click(within(group).getByRole('button', { name: 'Alpha Scopes' }))
    expect(await screen.findByText('Spyglass is not reachable.')).toBeInTheDocument()
    expect(within(group).getByRole('button', { name: 'Alpha Scopes' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByText(/^Paused Alpha Scopes/)).not.toBeInTheDocument()
  })

  it('ignores another click on a chip while its change is on the way', async () => {
    let finish: (value: unknown) => void = () => {}
    api.changeEntry.mockReturnValue(new Promise((resolve) => (finish = resolve)))
    renderPage()
    const group = await screen.findByRole('group', { name: 'Imaging AI' })
    fireEvent.click(within(group).getByRole('button', { name: 'Alpha Scopes' }))
    fireEvent.click(within(group).getByRole('button', { name: 'Alpha Scopes' }))
    expect(api.changeEntry).toHaveBeenCalledTimes(1)
    finish({})
    expect(await screen.findByText(/^Paused Alpha Scopes\./)).toBeInTheDocument()
  })

  it("offers Details, Move to another group, See its items and Remove in a chip's menu", async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'More actions for Alpha Scopes' }))
    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['Details', 'Move to another group…', 'See its items in the Feed', 'Remove…'])
  })

  it('shows the reason and the latest items in Details, above the form that edits the name', async () => {
    renderPage()
    await chooseFromChipMenu('Zeta Vision', 'Details')
    const dialog = screen.getByRole('dialog', { name: 'Zeta Vision' })
    expect(within(dialog).getByText(/^Company · Imaging AI · watched · last found \S/)).toBeInTheDocument()
    expect(within(dialog).getByText('Cleared a new endoscopy model.')).toBeInTheDocument()
    expect(within(dialog).getByRole('link', { name: 'Zeta Vision wins clearance' })).toHaveAttribute('href', '#/item/55')
    fireEvent.change(within(dialog).getByLabelText('Search query'), { target: { value: 'Zeta Vision endoscopy' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    await waitFor(() =>
      expect(api.changeEntry).toHaveBeenCalledWith(2, { name: 'Zeta Vision', kind: 'company', category: 'Imaging AI', query: 'Zeta Vision endoscopy' }),
    )
    await waitFor(() => expect(api.getWatch).toHaveBeenCalledTimes(2))
  })

  it('says in Details that a name has no items yet, and that it is paused', async () => {
    renderPage()
    await chooseFromChipMenu('FDA', 'Details')
    const dialog = screen.getByRole('dialog', { name: 'FDA' })
    expect(within(dialog).getByText('Regulator · Regulators · paused')).toBeInTheDocument()
    expect(within(dialog).getByText('No items mention it yet.')).toBeInTheDocument()
  })

  it('moves a name to another group, reloads the list, and Undo moves it back', async () => {
    renderPage()
    await chooseFromChipMenu('Alpha Scopes', 'Move to another group…')
    const dialog = screen.getByRole('dialog', { name: 'Move Alpha Scopes' })
    expect(within(dialog).getByText('Now in Imaging AI.')).toBeInTheDocument()
    expect(within(dialog).getByRole('radio', { name: 'Regulators' })).toBeChecked()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenCalledWith(1, { category: 'Regulators' }))
    await waitFor(() => expect(api.getWatch).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('Moved Alpha Scopes to Regulators.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenLastCalledWith(1, { category: 'Imaging AI' }))
    await waitFor(() => expect(api.getWatch).toHaveBeenCalledTimes(3))
  })

  it('shows a refused move inside the dialog', async () => {
    api.changeEntry.mockRejectedValue(new ApiError('That group name is too long.', { status: 422, kind: 'http', path: '/watch/1' }))
    renderPage()
    await chooseFromChipMenu('Alpha Scopes', 'Move to another group…')
    const dialog = screen.getByRole('dialog', { name: 'Move Alpha Scopes' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    expect(await within(dialog).findByText('That group name is too long.')).toBeInTheDocument()
    expect(api.getWatch).toHaveBeenCalledTimes(1)
  })

  it('opens the Feed searched for the name from "See its items in the Feed"', async () => {
    window.history.replaceState(null, '', '/#/watch')
    renderPage()
    await chooseFromChipMenu('Alpha Scopes', 'See its items in the Feed')
    expect(window.location.hash).toBe('#/feed?q=Alpha+Scopes')
  })
})

describe('the Add dialog', () => {
  it('offers the three ways to add in one small dialog', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Add' }))
    const dialog = screen.getByRole('dialog', { name: 'Add to Watch' })
    for (const name of [/Find who matters for a topic/, /Follow a topic/, /Add one organisation/]) {
      expect(within(dialog).getByRole('button', { name })).toBeInTheDocument()
    }
  })

  it('shows a waiting state while discovery runs, then says how many names were added', async () => {
    let finish: (value: DiscoverResult) => void = () => {}
    api.discoverTopic.mockReturnValue(new Promise<DiscoverResult>((resolve) => (finish = resolve)))
    renderPage()
    const dialog = await openAdd(/Find who matters for a topic/)
    fireEvent.change(within(dialog).getByLabelText('Topic'), { target: { value: 'surgical robots' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Find' }))
    expect(await within(dialog).findByText(/usually takes 30 to 60 seconds/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Topic')).toBeDisabled()
    finish({ suggested: [entry({ id: 20, name: 'New One', status: 'suggested' })], already_known: 2 })
    expect(await within(dialog).findByText('1 name added to Suggested. 2 were already on your list.')).toBeInTheDocument()
    expect(api.discoverTopic).toHaveBeenCalledWith('surgical robots')
    await waitFor(() => expect(api.getWatch).toHaveBeenCalledTimes(2))
  })

  it('reports a failed discovery in words', async () => {
    api.discoverTopic.mockRejectedValue(new ApiError('The model request failed; try again later', { status: 502, kind: 'http', path: '/watch/discover' }))
    renderPage()
    const dialog = await openAdd(/Find who matters for a topic/)
    fireEvent.change(within(dialog).getByLabelText('Topic'), { target: { value: 'agents' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Find' }))
    expect(await within(dialog).findByText('The model request failed; try again later')).toBeInTheDocument()
  })

  it('tells the reader in a toast when discovery finishes after the dialog was closed', async () => {
    let finish: (value: DiscoverResult) => void = () => {}
    api.discoverTopic.mockReturnValue(new Promise<DiscoverResult>((resolve) => (finish = resolve)))
    renderPage()
    const dialog = await openAdd(/Find who matters for a topic/)
    fireEvent.change(within(dialog).getByLabelText('Topic'), { target: { value: 'imaging' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Find' }))
    await within(dialog).findByText(/usually takes 30 to 60 seconds/)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    finish({ suggested: [entry({ id: 21, name: 'Later One', status: 'suggested' })] })
    expect(await screen.findByText('1 name added to Suggested.')).toBeInTheDocument()
  })

  it('follows a topic: creates a track with the name, search phrase and section', async () => {
    renderPage()
    const dialog = await openAdd(/Follow a topic/)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Follow' }))
    expect(await within(dialog).findByText('Give the topic a name first.')).toBeInTheDocument()
    expect(api.createTrack).not.toHaveBeenCalled()

    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'AI in drug discovery' } })
    fireEvent.change(within(dialog).getByLabelText('Search phrase'), { target: { value: '"drug discovery" AI' } })
    fireEvent.change(within(dialog).getByLabelText('Section'), { target: { value: 'industry' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Follow' }))
    await waitFor(() =>
      expect(api.createTrack).toHaveBeenCalledWith({ label: 'AI in drug discovery', query: '"drug discovery" AI', section: 'industry', kind: 'topic' }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(await screen.findByText('Now following AI in drug discovery')).toBeInTheDocument()
    await waitFor(() => expect(api.getTracks).toHaveBeenCalledTimes(2)) // the topics list reloads
  })

  it('searches for the name when the search phrase is left empty, and shows a refusal in the dialog', async () => {
    api.createTrack.mockRejectedValue(new ApiError('You already follow a track with this name.', { status: 409, kind: 'http', path: '/tracks' }))
    renderPage()
    const dialog = await openAdd(/Follow a topic/)
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Capsule endoscopy' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Follow' }))
    await waitFor(() => expect(api.createTrack).toHaveBeenCalledWith(expect.objectContaining({ query: 'Capsule endoscopy' })))
    expect(await within(dialog).findByText('You already follow a track with this name.')).toBeInTheDocument()
  })

  it('adds one organisation by hand and refuses an empty name', async () => {
    renderPage()
    const dialog = await openAdd(/Add one organisation/)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
    expect(await within(dialog).findByText('Give it a name first.')).toBeInTheDocument()
    expect(api.addEntry).not.toHaveBeenCalled()

    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Delta Corp' } })
    fireEvent.change(within(dialog).getByLabelText('Group'), { target: { value: 'Imaging AI' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
    await waitFor(() =>
      expect(api.addEntry).toHaveBeenCalledWith({ name: 'Delta Corp', kind: 'company', category: 'Imaging AI', query: null }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('shows the server message inside the dialog when adding fails, and Back returns to the choices', async () => {
    api.addEntry.mockRejectedValue(new ApiError('Delta Corp is already on your list', { status: 409, kind: 'http', path: '/watch' }))
    renderPage()
    const dialog = await openAdd(/Add one organisation/)
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Delta Corp' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
    expect(await within(dialog).findByText('Delta Corp is already on your list')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Back' }))
    expect(within(dialog).getByRole('button', { name: /Follow a topic/ })).toBeInTheDocument()
  })
})
