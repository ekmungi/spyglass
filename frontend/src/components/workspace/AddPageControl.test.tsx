// Tests for AddPageControl: inline URL input, add-and-judge flow,
// exists path, honest inline errors, and Escape cancel.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from '../../lib/api'
import { makeCard } from '../../test/fixtures'
import { AddPageControl } from './AddPageControl'

afterEach(() => vi.restoreAllMocks())

/** Render the control and expand its inline input; returns the spies. */
function renderExpanded() {
  const onPageAdded = vi.fn()
  render(<AddPageControl onPageAdded={onPageAdded} />)
  fireEvent.click(screen.getByRole('button', { name: /add page/i }))
  return { onPageAdded }
}

describe('AddPageControl', () => {
  it('starts collapsed and expands into a URL input on click', () => {
    render(<AddPageControl onPageAdded={() => {}} />)
    expect(screen.queryByPlaceholderText(/page url/i)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /add page/i }))
    expect(screen.getByPlaceholderText(/page url/i)).toBeInTheDocument()
  })

  it('adds a page, shows the judging label in flight, and hands the card up', async () => {
    const card = { ...makeCard({ id: 42, title: 'Fetched page' }), status: 'created' as const }
    let resolve!: (value: typeof card) => void
    vi.spyOn(api, 'addPage').mockReturnValue(new Promise((res) => { resolve = res }))
    const { onPageAdded } = renderExpanded()
    fireEvent.change(screen.getByPlaceholderText(/page url/i), {
      target: { value: 'https://example.com/post' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^add$/i }))
    // The POST enriches + judges and can take ~30s: the label says so.
    expect(screen.getByText(/adding & judging/i)).toBeInTheDocument()
    resolve(card)
    await waitFor(() => expect(onPageAdded).toHaveBeenCalledWith(card))
    expect(api.addPage).toHaveBeenCalledWith('https://example.com/post')
    // Success collapses the control back to the affordance.
    expect(screen.queryByPlaceholderText(/page url/i)).not.toBeInTheDocument()
  })

  it('treats an already-collected page (status exists) the same as created', async () => {
    const card = { ...makeCard({ id: 7 }), status: 'exists' as const }
    vi.spyOn(api, 'addPage').mockResolvedValue(card)
    const { onPageAdded } = renderExpanded()
    fireEvent.change(screen.getByPlaceholderText(/page url/i), {
      target: { value: 'https://example.com/dup' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^add$/i }))
    await waitFor(() => expect(onPageAdded).toHaveBeenCalledWith(card))
  })

  it('shows an honest inline error and keeps the input on failure', async () => {
    vi.spyOn(api, 'addPage').mockRejectedValue(new Error('That does not look like a valid URL.'))
    const { onPageAdded } = renderExpanded()
    const input = screen.getByPlaceholderText(/page url/i)
    fireEvent.change(input, { target: { value: 'not-a-url' } })
    fireEvent.click(screen.getByRole('button', { name: /^add$/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/valid url/i)
    // The input stays, still holding the typed value for correction.
    expect((screen.getByPlaceholderText(/page url/i) as HTMLInputElement).value).toBe('not-a-url')
    expect(onPageAdded).not.toHaveBeenCalled()
  })

  it('submits on Enter', async () => {
    const card = { ...makeCard({ id: 8 }), status: 'created' as const }
    vi.spyOn(api, 'addPage').mockResolvedValue(card)
    const { onPageAdded } = renderExpanded()
    const input = screen.getByPlaceholderText(/page url/i)
    fireEvent.change(input, { target: { value: 'https://example.com/enter' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onPageAdded).toHaveBeenCalledWith(card))
  })

  it('Escape cancels and collapses the input', () => {
    renderExpanded()
    const input = screen.getByPlaceholderText(/page url/i)
    fireEvent.change(input, { target: { value: 'https://example.com' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.queryByPlaceholderText(/page url/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add page/i })).toBeInTheDocument()
  })

  it('the cancel button collapses the input too', () => {
    renderExpanded()
    fireEvent.click(screen.getByRole('button', { name: /cancel add page/i }))
    expect(screen.queryByPlaceholderText(/page url/i)).not.toBeInTheDocument()
  })
})
