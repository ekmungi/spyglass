// Tests for the Watch page: layout, the Add dialog's three paths, suggestions, per-name actions and errors.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import { ToastViewport } from '../../ui'
import WatchPage from '../WatchPage'
import { clearLoadCache } from '../sources/useLoad'
import type { DiscoverResult } from './api'
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

/** Open the Add dialog and choose one of its three paths. */
async function openAdd(path: string | RegExp) {
  fireEvent.click(await screen.findByRole('button', { name: 'Add' }))
  const dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: path }))
  return screen.getByRole('dialog')
}

beforeEach(() => {
  clearLoadCache()
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

  it('shows suggestions first, then groups with recently mentioned names ahead of the rest', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Suggested' })).toBeInTheDocument()
    expect(screen.getByText('Gamma Labs')).toBeInTheDocument()
    const headings = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent)
    expect(headings.slice(0, 4)).toEqual(['Topics you follow', 'You are not following any topics yet', 'Suggested', 'Imaging AI'])

    const group = screen.getByRole('region', { name: 'Imaging AI' })
    const names = within(group).getAllByText(/^(Alpha Scopes|Zeta Vision)$/).map((node) => node.textContent)
    expect(names).toEqual(['Zeta Vision', 'Alpha Scopes'])
    expect(within(group).getByText(/Last mentioned/)).toBeInTheDocument()
    expect(within(group).getByRole('link', { name: 'Zeta Vision wins clearance' })).toHaveAttribute('href', '#/item/55')
  })

  it('says how many items each group brought into the Feed this week', async () => {
    renderPage()
    const group = await screen.findByRole('region', { name: 'Imaging AI' })
    expect(within(group).getByText('3 items this week')).toBeInTheDocument()
  })

  it('shows a group whose names are all muted as paused, with a Resume action', async () => {
    renderPage()
    const group = await screen.findByRole('region', { name: 'Regulators' })
    expect(within(group).getByText('Paused')).toBeInTheDocument()
    expect(within(group).getByRole('button', { name: 'Resume Regulators' })).toBeInTheDocument()
    expect(within(group).getByText('FDA')).toBeInTheDocument()
    expect(screen.queryByText(/^Muted \(/)).not.toBeInTheDocument()
  })

  it('keeps a name muted inside a followed group in a collapsed pile at the end', async () => {
    const mixed = register()
    mixed.categories[0].entities.push(entry({ id: 4, name: 'Old Scopes', status: 'muted' }))
    api.getWatch.mockResolvedValue(mixed)
    renderPage()
    const summary = await screen.findByText('Muted (1)')
    expect(summary.closest('details')).not.toHaveAttribute('open')
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

  it('edits a name through its menu and sends the search query', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Actions for Alpha Scopes' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Search query'), { target: { value: 'Alpha Scopes polyp' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    await waitFor(() =>
      expect(api.changeEntry).toHaveBeenCalledWith(1, { name: 'Alpha Scopes', kind: 'company', category: 'Imaging AI', query: 'Alpha Scopes polyp' }),
    )
  })

  it('asks before removing a name', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Actions for Alpha Scopes' }))
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
    api.getWatch.mockResolvedValue({ categories: [], suggested: [] })
    renderPage()
    expect(await screen.findByText('Nothing on your watch list yet')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add something to watch' }))
    expect(within(screen.getByRole('dialog')).getByRole('button', { name: /Find who matters for a topic/ })).toBeInTheDocument()
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
