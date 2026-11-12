// Tests for the Add link dialog: adding a link, then offering "Follow more like this" for the same address.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RadarItem } from '../api/types'
import { AddLinkDialog } from './AddLinkDialog'

const api = vi.hoisted(() => ({ captureLink: vi.fn(), suggestTracksForUrl: vi.fn(), createTrack: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

const added = { id: 300, headline: 'The page', title: 'The page', origin: 'example.org' } as RadarItem

beforeEach(() => {
  vi.clearAllMocks()
  api.captureLink.mockResolvedValue(added)
  api.suggestTracksForUrl.mockResolvedValue({
    mode: 'ai',
    suggestions: [{ label: 'Surgical robotics', query: 'surgical robotics', kind: 'topic', section: 'health', section_label: 'Health', why: 'The field.', already_followed: false }],
    similar: [],
    item: added,
  })
  api.createTrack.mockResolvedValue({ id: 1, new_items: 2 })
})

function addTheLink(onClose = vi.fn()) {
  render(<AddLinkDialog open onClose={onClose} />)
  fireEvent.change(screen.getByLabelText('Web address'), { target: { value: 'https://example.org/page' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add link' }))
  return onClose
}

describe('AddLinkDialog', () => {
  it('refuses an address that is not http or https', () => {
    render(<AddLinkDialog open onClose={() => undefined} />)
    fireEvent.change(screen.getByLabelText('Web address'), { target: { value: 'ftp://x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add link' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a full web address')
    expect(api.captureLink).not.toHaveBeenCalled()
  })

  it('confirms the link and offers Done, Open and "Follow more like this"', async () => {
    addTheLink()
    expect(await screen.findByRole('dialog', { name: 'Link added' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Follow more like this' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open' })).toBeInTheDocument()
    expect(api.suggestTracksForUrl).not.toHaveBeenCalled()
  })

  it('runs the suggestion for the same address and follows with the new item id', async () => {
    addTheLink()
    fireEvent.click(await screen.findByRole('button', { name: 'Follow more like this' }))
    expect(await screen.findByRole('dialog', { name: 'Follow more like this' })).toBeInTheDocument()
    expect(api.suggestTracksForUrl).toHaveBeenCalledWith('https://example.org/page', expect.anything())
    await screen.findByRole('checkbox', { name: 'Surgical robotics' })
    fireEvent.click(screen.getByRole('button', { name: 'Follow selected' }))
    await waitFor(() => expect(api.createTrack).toHaveBeenCalledWith(expect.objectContaining({ label: 'Surgical robotics', from_item_id: 300 })))
  })

  it('closes from Done', async () => {
    const onClose = addTheLink()
    fireEvent.click(await screen.findByRole('button', { name: 'Done' }))
    expect(onClose).toHaveBeenCalled()
  })
})
