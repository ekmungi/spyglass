// Tests for the Find papers page: chips, the waiting state, results, adding to the feed, memory and errors.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import type { PapersResponse, PaperResult } from '../../api/types'
import PapersPage from '../PapersPage'
import { resetPapersMemory } from './store'

const api = vi.hoisted(() => ({
  searchPapers: vi.fn(),
  captureLink: vi.fn(),
  loadProfileTopics: vi.fn(),
}))
vi.mock('./api', () => api)

function paper(over: Partial<PaperResult> = {}): PaperResult {
  return {
    title: 'Scaling laws for endoscopic polyp detection',
    authors: ['A. Rivera', 'B. Chen', 'C. Okafor', 'D. Novak'],
    published: '2026-10-30T00:00:00Z',
    url: 'https://arxiv.org/abs/2610.00001',
    pdf_url: 'https://arxiv.org/pdf/2610.00001',
    abstract: 'We study how detection quality grows with data.',
    why: 'Relevant to your interest in medical imaging AI.',
    signal: '312 upvotes on Hugging Face',
    item_id: null,
    ...over,
  }
}

function searchBox() {
  return screen.getByLabelText('What do you want to read about?')
}

beforeEach(() => {
  vi.clearAllMocks()
  resetPapersMemory()
  api.loadProfileTopics.mockResolvedValue(['Agents', 'Imaging AI', 'Regulation', 'Evaluation', 'Fifth topic'])
  api.captureLink.mockResolvedValue({ id: 77 })
})

describe('PapersPage', () => {
  it('offers at most four example chips taken from the profile topics', async () => {
    render(<PapersPage />)
    const group = await screen.findByRole('group', { name: 'Topics from your profile' })
    expect(within(group).getAllByRole('button').map((node) => node.textContent)).toEqual(['Agents', 'Imaging AI', 'Regulation', 'Evaluation'])
  })

  it('shows an honest waiting state, then ranked results with the reason, signal and actions', async () => {
    let finish: (value: PapersResponse) => void = () => {}
    api.searchPapers.mockReturnValue(new Promise<PapersResponse>((resolve) => (finish = resolve)))
    render(<PapersPage />)
    fireEvent.change(searchBox(), { target: { value: 'polyp detection' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    expect(await screen.findByText(/usually takes 10 to 40 seconds/)).toBeInTheDocument()
    expect(searchBox()).toBeDisabled()

    finish({ papers: [paper(), paper({ title: 'In the feed already', url: 'https://x.org/2', pdf_url: null, item_id: 5, signal: null, why: null })] })
    expect(await screen.findByText('Scaling laws for endoscopic polyp detection')).toBeInTheDocument()
    expect(api.searchPapers).toHaveBeenCalledWith('polyp detection', 8)
    // The date wording follows the machine's locale, so only the author part is exact.
    expect(screen.getAllByText(/^A\. Rivera, B\. Chen, C\. Okafor and 1 other · \S+/)).toHaveLength(2)
    expect(screen.getByText('Relevant to your interest in medical imaging AI.')).toBeInTheDocument()
    expect(screen.getByText('312 upvotes on Hugging Face')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'PDF' })).toHaveAttribute('href', 'https://arxiv.org/pdf/2610.00001')
    const links = screen.getAllByRole('link', { name: 'Open' })
    expect(links[0]).toHaveAttribute('href', 'https://arxiv.org/abs/2610.00001')
    expect(links[0]).toHaveAttribute('target', '_blank')
    expect(links[1]).toHaveAttribute('href', '#/item/5')
    expect(screen.getByText('In your feed')).toBeInTheDocument()
  })

  it('runs a search when an example chip is chosen', async () => {
    api.searchPapers.mockResolvedValue({ papers: [paper()] })
    render(<PapersPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Imaging AI' }))
    await waitFor(() => expect(api.searchPapers).toHaveBeenCalledWith('Imaging AI', 8))
    expect(searchBox()).toHaveValue('Imaging AI')
  })

  it('adds a paper to the feed and then opens it in the reader', async () => {
    api.searchPapers.mockResolvedValue({ papers: [paper()] })
    render(<PapersPage />)
    fireEvent.change(searchBox(), { target: { value: 'polyps' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add to my feed' }))
    await waitFor(() => expect(api.captureLink).toHaveBeenCalledWith({ url: 'https://arxiv.org/abs/2610.00001' }))
    expect(await screen.findByText('Added to your feed')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '#/item/77')
  })

  it('says so when adding to the feed fails and lets the reader try again', async () => {
    api.searchPapers.mockResolvedValue({ papers: [paper()] })
    api.captureLink.mockRejectedValueOnce(new ApiError('Spyglass could not fetch that page.', { status: 502, kind: 'http', path: '/capture' }))
    render(<PapersPage />)
    fireEvent.change(searchBox(), { target: { value: 'polyps' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add to my feed' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Spyglass could not fetch that page.')
    expect(screen.getByRole('button', { name: 'Add to my feed' })).toBeEnabled()
  })

  it('keeps the last result when the reader leaves the page and comes back', async () => {
    api.searchPapers.mockResolvedValue({ papers: [paper()] })
    const first = render(<PapersPage />)
    fireEvent.change(searchBox(), { target: { value: 'polyps' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    await screen.findByText('Scaling laws for endoscopic polyp detection')
    first.unmount()

    render(<PapersPage />)
    expect(screen.getByText('Scaling laws for endoscopic polyp detection')).toBeInTheDocument()
    expect(searchBox()).toHaveValue('polyps')
    expect(api.searchPapers).toHaveBeenCalledTimes(1)
  })

  it('shows an empty state when nothing matched', async () => {
    api.searchPapers.mockResolvedValue({ papers: [] })
    render(<PapersPage />)
    fireEvent.change(searchBox(), { target: { value: 'zzzz' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    expect(await screen.findByText('No papers matched this topic.')).toBeInTheDocument()
  })

  it('shows the service notice for an empty search', async () => {
    api.searchPapers.mockResolvedValue({ papers: [], status: 'empty', notice: 'The paper index did not answer, so nothing could be searched.' })
    render(<PapersPage />)
    fireEvent.change(searchBox(), { target: { value: 'zzzz' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    expect(await screen.findByText('No papers matched this topic.')).toBeInTheDocument()
    expect(screen.getByText('The paper index did not answer, so nothing could be searched.')).toBeInTheDocument()
  })

  it('shows a degraded notice above the results', async () => {
    api.searchPapers.mockResolvedValue({ papers: [paper()], status: 'degraded', notice: 'Ranking was not available; papers are in date order.' })
    render(<PapersPage />)
    fireEvent.change(searchBox(), { target: { value: 'polyps' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    const notice = await screen.findByText('Ranking was not available; papers are in date order.')
    const heading = screen.getByRole('heading', { name: /Results for/ })
    expect(notice.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows the failure in words and retries the same topic', async () => {
    api.searchPapers.mockRejectedValueOnce(new ApiError('Spyglass or a service it relies on is not responding. Try again shortly.', { status: 503, kind: 'http', path: '/papers/search' }))
    api.searchPapers.mockResolvedValueOnce({ papers: [paper()] })
    render(<PapersPage />)
    fireEvent.change(searchBox(), { target: { value: 'polyps' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not responding')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Scaling laws for endoscopic polyp detection')).toBeInTheDocument()
    expect(api.searchPapers).toHaveBeenLastCalledWith('polyps', 8)
  })

  it('still searches when the profile topics cannot be loaded', async () => {
    api.loadProfileTopics.mockRejectedValue(new Error('offline'))
    api.searchPapers.mockResolvedValue({ papers: [paper()] })
    render(<PapersPage />)
    expect(screen.queryByRole('group', { name: 'Topics from your profile' })).not.toBeInTheDocument()
    fireEvent.change(searchBox(), { target: { value: 'polyps' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    expect(await screen.findByText('Scaling laws for endoscopic polyp detection')).toBeInTheDocument()
  })
})
