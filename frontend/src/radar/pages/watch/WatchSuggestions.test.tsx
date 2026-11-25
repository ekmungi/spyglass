// Tests for the suggestions on the Watch page: one row of chips per profile section with counts, watch
// and undo in place, the cross that marks a name not of interest, "Hide the rest for good", and the
// collapsed Not of interest list that takes a name back.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import { ToastViewport } from '../../ui'
import WatchPage from '../WatchPage'
import { clearLoadCache } from '../sources/useLoad'
import type { WatchRegister } from './api'
import { clearToasts, suggestionRegister } from './testFixtures'

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
  setSuggestionStatus: vi.fn(),
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

/** The Suggested section, once the register has loaded. */
const suggestedSection = () => screen.findByRole('region', { name: 'Suggested this month' })

/** One row of the Suggested section, found by its heading. */
const row = (section: HTMLElement, label: string) => within(section).getByRole('group', { name: label })

/** The outer pill of a chip, which carries its look. */
const pill = (button: HTMLElement) => button.closest('.rw-chip') as HTMLElement

/** The Undo button of the toast that says `message`. */
const undoOf = (message: string) => within(screen.getByText(message).closest('.r-toast') as HTMLElement).getByRole('button', { name: 'Undo' })

beforeEach(() => {
  clearLoadCache()
  clearToasts()
  vi.clearAllMocks()
  api.getWatch.mockResolvedValue(suggestionRegister())
  api.changeEntry.mockResolvedValue({})
  api.getTracks.mockResolvedValue([])
  api.setSuggestionStatus.mockImplementation((ids: number[]) => Promise.resolve({ ...suggestionRegister(), changed: ids }))
})

describe('Suggested', () => {
  it('shows a row for each profile section that holds names, then the topic search and Other, each chip with its count', async () => {
    renderPage()
    const section = await suggestedSection()
    expect(within(section).getByText('up to 5 per section of your profile')).toBeInTheDocument()
    const labels = within(section)
      .getAllByRole('group')
      .map((node) => within(node).getByRole('heading', { level: 3 }).textContent)
    expect(labels).toEqual(['Healthcare AI & medtech', 'Industry & use cases', 'From your search: RSNA', 'Other'])

    // Most-named first inside a row; the count is on the chip.
    const health = row(section, 'Healthcare AI & medtech')
    const chips = within(health).getAllByRole('button', { pressed: false })
    expect(chips.map((node) => node.getAttribute('aria-label'))).toEqual(['NHS England, named in 15 items', 'Oura, named in 9 items'])
    expect(within(chips[0]).getByText('15')).toBeInTheDocument()
    expect(within(row(section, 'From your search: RSNA')).getByRole('button', { name: 'Aidoc' })).toBeInTheDocument()
    expect(within(section).getByText('kept for 30 days')).toBeInTheDocument()
    expect(within(section).getByText('5 undecided')).toBeInTheDocument()
  })

  it('watches a suggestion with one click, in place, and a second click undoes it', async () => {
    renderPage()
    const section = await suggestedSection()
    const health = row(section, 'Healthcare AI & medtech')
    fireEvent.click(within(health).getByRole('button', { name: 'NHS England, named in 15 items' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenCalledWith(20, { status: 'active' }))
    expect(within(health).getByRole('button', { name: 'NHS England, named in 15 items' })).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByText('Watching NHS England. It joins Regulators.')).toBeInTheDocument()
    expect(within(section).getByText('4 undecided · 1 now watched, in their group on your next visit')).toBeInTheDocument()
    // A watched chip has no cross, nothing reloads, and the name joins Watching only on the next visit.
    expect(within(health).queryByRole('button', { name: 'Not of interest: NHS England' })).not.toBeInTheDocument()
    expect(api.getWatch).toHaveBeenCalledTimes(1)
    expect(within(screen.getByRole('region', { name: 'Watching' })).queryByText('NHS England')).not.toBeInTheDocument()

    fireEvent.click(within(health).getByRole('button', { name: 'NHS England, named in 15 items' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenLastCalledWith(20, { status: 'suggested' }))
    expect(await screen.findByText('No longer watching NHS England.')).toBeInTheDocument()
    expect(within(health).getByRole('button', { name: 'NHS England, named in 15 items' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('names "Other" as the group of a watched suggestion that fits none', async () => {
    renderPage()
    fireEvent.click(within(row(await suggestedSection(), 'Healthcare AI & medtech')).getByRole('button', { name: 'Oura, named in 9 items' }))
    expect(await screen.findByText('Watching Oura. It joins Other.')).toBeInTheDocument()
  })

  it('marks a name not of interest with the cross: the chip stays in its row, struck through, and Undo takes it back', async () => {
    renderPage()
    const health = row(await suggestedSection(), 'Healthcare AI & medtech')
    fireEvent.click(within(health).getByRole('button', { name: 'Not of interest: Oura' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenCalledWith(21, { status: 'rejected' }))
    expect(pill(within(health).getByRole('button', { name: 'Oura, named in 9 items, not of interest' }))).toHaveClass('rw-chip--rej')
    expect(within(health).getByRole('button', { name: 'Take back Oura' })).toBeInTheDocument()
    expect(await screen.findByText('Oura will not be suggested again.')).toBeInTheDocument()
    // It joins the Not of interest list at once, after the name rejected on an earlier visit.
    expect(screen.getByText('Not of interest (2)')).toBeInTheDocument()

    fireEvent.click(undoOf('Oura will not be suggested again.'))
    await waitFor(() => expect(api.changeEntry).toHaveBeenLastCalledWith(21, { status: 'suggested' }))
    expect(await within(health).findByRole('button', { name: 'Not of interest: Oura' })).toBeInTheDocument()
    expect(screen.getByText('Not of interest (1)')).toBeInTheDocument()
  })

  it('lists a name crossed on a first visit in Not of interest at once, while its chip stays struck in its row', async () => {
    api.getWatch.mockResolvedValue({ ...suggestionRegister(), rejected: [] })
    renderPage()
    const health = row(await suggestedSection(), 'Healthcare AI & medtech')
    expect(screen.getByText('Not of interest (0)')).toBeInTheDocument()
    fireEvent.click(within(health).getByRole('button', { name: 'Not of interest: Oura' }))
    const list = (await screen.findByText('Not of interest (1)')).closest('details') as HTMLElement
    expect(within(list).getByRole('button', { name: 'Take back Oura' })).toBeInTheDocument()
    expect(within(list).queryByText(/^Nothing yet/)).not.toBeInTheDocument()
    expect(pill(within(health).getByRole('button', { name: 'Oura, named in 9 items, not of interest' }))).toHaveClass('rw-chip--rej')
  })

  it('reopens the chip in its row when a name struck on this visit is taken back from the list', async () => {
    renderPage()
    const health = row(await suggestedSection(), 'Healthcare AI & medtech')
    fireEvent.click(within(health).getByRole('button', { name: 'Not of interest: Oura' }))
    await screen.findByText('Oura will not be suggested again.')
    const list = screen.getByText('Not of interest (2)').closest('details') as HTMLElement
    fireEvent.click(within(list).getByRole('button', { name: 'Take back Oura' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenLastCalledWith(21, { status: 'suggested' }))
    expect(await screen.findByText('Oura is a suggestion again.')).toBeInTheDocument()
    expect(within(health).getByRole('button', { name: 'Not of interest: Oura' })).toBeInTheDocument()
    expect(screen.getByText('Not of interest (1)')).toBeInTheDocument()
    expect(within(list).queryByRole('button', { name: 'Take back Oura' })).not.toBeInTheDocument()
  })

  it('does not undo a cross once the name has been watched since', async () => {
    renderPage()
    const health = row(await suggestedSection(), 'Healthcare AI & medtech')
    fireEvent.click(within(health).getByRole('button', { name: 'Not of interest: Oura' }))
    await screen.findByText('Oura will not be suggested again.')
    fireEvent.click(within(health).getByRole('button', { name: 'Oura, named in 9 items, not of interest' }))
    await screen.findByText('Oura is a suggestion again.')
    fireEvent.click(within(health).getByRole('button', { name: 'Oura, named in 9 items' }))
    await screen.findByText('Watching Oura. It joins Other.')
    expect(api.changeEntry).toHaveBeenCalledTimes(3)

    fireEvent.click(undoOf('Oura will not be suggested again.'))
    // The late Undo sends nothing, so Oura stays watched.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(api.changeEntry).toHaveBeenCalledTimes(3)
    expect(within(health).getByRole('button', { name: 'Oura, named in 9 items' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('takes a struck name back with a click on the chip', async () => {
    renderPage()
    const health = row(await suggestedSection(), 'Healthcare AI & medtech')
    fireEvent.click(within(health).getByRole('button', { name: 'Not of interest: Oura' }))
    await screen.findByText('Oura will not be suggested again.')
    fireEvent.click(within(health).getByRole('button', { name: 'Oura, named in 9 items, not of interest' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenLastCalledWith(21, { status: 'suggested' }))
    expect(await screen.findByText('Oura is a suggestion again.')).toBeInTheDocument()
    expect(pill(within(health).getByRole('button', { name: 'Oura, named in 9 items' }))).toHaveClass('rw-chip--sug')
  })

  it('hides every undecided suggestion for good in one call, and its Undo takes them all back', async () => {
    renderPage()
    const section = await suggestedSection()
    fireEvent.click(within(section).getByRole('button', { name: 'NHS England, named in 15 items' }))
    fireEvent.click(within(section).getByRole('button', { name: 'Not of interest: Oura' }))
    await screen.findByText('Oura will not be suggested again.')

    fireEvent.click(within(section).getByRole('button', { name: 'Hide the rest for good' }))
    await waitFor(() => expect(api.setSuggestionStatus).toHaveBeenCalledWith([22, 23, 24], 'rejected'))
    expect(await screen.findByText('3 names will not be suggested again.')).toBeInTheDocument()
    expect(pill(within(section).getByRole('button', { name: 'Novartis, named in 24 items, not of interest' }))).toHaveClass('rw-chip--rej')
    expect(within(section).getByRole('button', { name: 'Hide the rest for good' })).toBeDisabled()
    expect(within(section).getByText('0 undecided · 1 now watched, in their group on your next visit')).toBeInTheDocument()

    fireEvent.click(undoOf('3 names will not be suggested again.'))
    await waitFor(() => expect(api.setSuggestionStatus).toHaveBeenLastCalledWith([22, 23, 24], 'suggested'))
    expect(await within(section).findByRole('button', { name: 'Not of interest: Novartis' })).toBeInTheDocument()
    expect(within(section).getByRole('button', { name: 'Not of interest: Aidoc' })).toBeInTheDocument()
  })

  it('raises the Not of interest count by the number of names hidden, and lists them', async () => {
    renderPage()
    const section = await suggestedSection()
    expect(screen.getByText('Not of interest (1)')).toBeInTheDocument()
    fireEvent.click(within(section).getByRole('button', { name: 'Hide the rest for good' }))
    await screen.findByText('5 names will not be suggested again.')
    const list = screen.getByText('Not of interest (6)').closest('details') as HTMLElement
    const names = within(list)
      .getAllByRole('button')
      .map((node) => node.getAttribute('aria-label'))
    // The names of earlier visits first, then the ones struck on this visit in the order of the rows.
    expect(names).toEqual(['Take back Old News Corp', 'Take back NHS England', 'Take back Oura', 'Take back Novartis', 'Take back Aidoc', 'Take back Stray Org'])
  })

  it('leaves out a name whose take-back is still on its way when the rest is hidden', async () => {
    api.changeEntry.mockImplementation((id: number, body: { status?: string }) =>
      id === 21 && body.status === 'suggested' ? new Promise(() => {}) : Promise.resolve({}),
    )
    renderPage()
    const section = await suggestedSection()
    fireEvent.click(within(section).getByRole('button', { name: 'Not of interest: Oura' }))
    await screen.findByText('Oura will not be suggested again.')
    fireEvent.click(within(section).getByRole('button', { name: 'Take back Oura' }))
    expect(pill(within(section).getByRole('button', { name: 'Oura, named in 9 items' }))).toHaveAttribute('aria-busy', 'true')

    fireEvent.click(within(section).getByRole('button', { name: 'Hide the rest for good' }))
    await waitFor(() => expect(api.setSuggestionStatus).toHaveBeenCalledWith([20, 22, 23, 24], 'rejected'))
  })

  it("does not undo hiding a name that was taken back and watched since, and leaves the service's answer alone", async () => {
    renderPage()
    const section = await suggestedSection()
    fireEvent.click(within(section).getByRole('button', { name: 'Hide the rest for good' }))
    await screen.findByText('5 names will not be suggested again.')
    fireEvent.click(within(section).getByRole('button', { name: 'Novartis, named in 24 items, not of interest' }))
    await screen.findByText('Novartis is a suggestion again.')
    fireEvent.click(within(section).getByRole('button', { name: 'Novartis, named in 24 items' }))
    await screen.findByText('Watching Novartis. It joins Pharma AI.')

    fireEvent.click(undoOf('5 names will not be suggested again.'))
    // Only the names that still look hidden are taken back; Novartis stays watched and is not sent.
    await waitFor(() => expect(api.setSuggestionStatus).toHaveBeenLastCalledWith([20, 21, 23, 24], 'suggested'))
    expect(api.changeEntry).toHaveBeenCalledTimes(2)
    expect(await within(section).findByRole('button', { name: 'Not of interest: Aidoc' })).toBeInTheDocument()
    expect(within(section).getByRole('button', { name: 'Novartis, named in 24 items' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('counts and offers to undo only the names whose status really changed', async () => {
    api.setSuggestionStatus.mockResolvedValue({ ...suggestionRegister(), changed: [22] })
    renderPage()
    const section = await suggestedSection()
    fireEvent.click(within(section).getByRole('button', { name: 'Hide the rest for good' }))
    expect(await screen.findByText('1 name will not be suggested again.')).toBeInTheDocument()
    expect(pill(within(section).getByRole('button', { name: 'Novartis, named in 24 items, not of interest' }))).toHaveClass('rw-chip--rej')
    expect(within(section).getByRole('button', { name: 'Not of interest: Aidoc' })).toBeInTheDocument()

    fireEvent.click(undoOf('1 name will not be suggested again.'))
    await waitFor(() => expect(api.setSuggestionStatus).toHaveBeenLastCalledWith([22], 'suggested'))
  })

  it('puts a suggestion back and says why when the change fails', async () => {
    api.changeEntry.mockRejectedValue(new ApiError('Spyglass is not reachable.', { status: 0, kind: 'network', path: '/watch/20' }))
    renderPage()
    const health = row(await suggestedSection(), 'Healthcare AI & medtech')
    fireEvent.click(within(health).getByRole('button', { name: 'NHS England, named in 15 items' }))
    expect(await screen.findByText('Spyglass is not reachable.')).toBeInTheDocument()
    expect(within(health).getByRole('button', { name: 'NHS England, named in 15 items' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByText(/^Watching NHS England/)).not.toBeInTheDocument()
  })

  it('puts every chip back and says why when hiding the rest fails', async () => {
    api.setSuggestionStatus.mockRejectedValue(new ApiError('Spyglass is not reachable.', { status: 0, kind: 'network', path: '/watch/suggestions/status' }))
    renderPage()
    const section = await suggestedSection()
    fireEvent.click(within(section).getByRole('button', { name: 'Hide the rest for good' }))
    expect(await screen.findByText('Spyglass is not reachable.')).toBeInTheDocument()
    expect(within(section).getByRole('button', { name: 'Not of interest: Novartis' })).toBeInTheDocument()
    expect(within(section).getByText('5 undecided')).toBeInTheDocument()
  })

  it('keeps a suggestion watched on this visit in its row when the quiet refresh of a revisit lands', async () => {
    const first = renderPage()
    await suggestedSection()
    first.unmount()
    let answer: (value: WatchRegister) => void = () => {}
    api.getWatch.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)))
    renderPage()
    const section = await suggestedSection()
    fireEvent.click(within(row(section, 'Healthcare AI & medtech')).getByRole('button', { name: 'NHS England, named in 15 items' }))
    await screen.findByText('Watching NHS England. It joins Regulators.')

    // The fresh answer already has NHS England watched, in its group.
    const fresh = suggestionRegister()
    const nhs = fresh.suggested.find((e) => e.id === 20)!
    fresh.suggested = fresh.suggested.filter((e) => e.id !== 20).map((e) => (e.id === 22 ? { ...e, count: 25 } : e))
    fresh.categories[1] = { ...fresh.categories[1], paused: false, entities: [...fresh.categories[1].entities, { ...nhs, status: 'active' }] }
    answer(fresh)
    await within(section).findByRole('button', { name: 'Novartis, named in 25 items' })
    expect(within(row(section, 'Healthcare AI & medtech')).getByRole('button', { name: 'NHS England, named in 15 items' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('group', { name: 'Regulators' })).not.toBeInTheDocument()
  })

  it('shows a name watched on this visit in its group, and one rejected in Not of interest, on the next visit', async () => {
    const view = renderPage()
    const section = await suggestedSection()
    fireEvent.click(within(section).getByRole('button', { name: 'NHS England, named in 15 items' }))
    fireEvent.click(within(section).getByRole('button', { name: 'Not of interest: Oura' }))
    await screen.findByText('Oura will not be suggested again.')
    view.unmount()

    // The fresh answer has not arrived yet, so the page shows the one it remembered.
    api.getWatch.mockReturnValue(new Promise(() => {}))
    renderPage()
    const group = await screen.findByRole('group', { name: 'Regulators' })
    expect(within(group).getByRole('button', { name: 'NHS England' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('Not of interest (2)')).toBeInTheDocument()
    const suggested = await suggestedSection()
    expect(within(suggested).queryByText('NHS England')).not.toBeInTheDocument()
    expect(within(suggested).queryByText('Oura')).not.toBeInTheDocument()
  })
})

describe('Not of interest', () => {
  it('lists the names rejected on earlier visits in a collapsed list and takes one back, with Undo', async () => {
    renderPage()
    const list = (await screen.findByText('Not of interest (1)')).closest('details') as HTMLElement
    expect(list).not.toHaveAttribute('open')
    expect(within(list).getByText('These are never suggested again. Take a name back to allow it.')).toBeInTheDocument()
    fireEvent.click(within(list).getByRole('button', { name: 'Take back Old News Corp' }))
    await waitFor(() => expect(api.changeEntry).toHaveBeenCalledWith(30, { status: 'suggested' }))
    expect(await screen.findByText('Old News Corp is a suggestion again.')).toBeInTheDocument()
    expect(screen.getByText('Not of interest (0)')).toBeInTheDocument()
    expect(within(list).queryByRole('button', { name: 'Take back Old News Corp' })).not.toBeInTheDocument()

    fireEvent.click(undoOf('Old News Corp is a suggestion again.'))
    await waitFor(() => expect(api.changeEntry).toHaveBeenLastCalledWith(30, { status: 'rejected' }))
    expect(await screen.findByText('Not of interest (1)')).toBeInTheDocument()
  })

  it('says what the list is for while it is empty', async () => {
    api.getWatch.mockResolvedValue({ ...suggestionRegister(), rejected: [] })
    renderPage()
    const list = (await screen.findByText('Not of interest (0)')).closest('details') as HTMLElement
    expect(within(list).getByText('Nothing yet. A name you mark with the cross is listed here and is never suggested again.')).toBeInTheDocument()
  })
})
