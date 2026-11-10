// Tests for ImportExportBar: file import and OPML/markdown export.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../lib/api'
import { ImportExportBar } from './ImportExportBar'

vi.mock('../lib/api')

describe('ImportExportBar', () => {
  const onRefresh = vi.fn()

  beforeEach(() => {
    vi.mocked(api.importFeeds).mockResolvedValue({ added: 3, skipped: 1 })
    vi.mocked(api.exportFeeds).mockResolvedValue('<?xml version="1.0"?><opml/>')
    onRefresh.mockClear()
  })

  it('renders export OPML and Markdown buttons', () => {
    render(<ImportExportBar onRefresh={onRefresh} />)
    expect(screen.getByRole('button', { name: /export opml/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /export markdown/i })).toBeInTheDocument()
  })

  it('renders a file input for import', () => {
    render(<ImportExportBar onRefresh={onRefresh} />)
    expect(screen.getByLabelText(/import/i)).toBeInTheDocument()
  })

  it('choosing a file calls importFeeds with text content and refreshes', async () => {
    render(<ImportExportBar onRefresh={onRefresh} />)
    const fileInput = screen.getByLabelText(/import/i)
    const content = '<opml version="2.0"/>'
    const file = new File([content], 'feeds.opml', { type: 'text/xml' })
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })
    // Mock file.text()
    vi.spyOn(file, 'text').mockResolvedValue(content)
    fireEvent.change(fileInput)
    await waitFor(() => expect(api.importFeeds).toHaveBeenCalledWith(content))
    await waitFor(() => expect(onRefresh).toHaveBeenCalled())
  })

  it('shows added/skipped result after import', async () => {
    render(<ImportExportBar onRefresh={onRefresh} />)
    const fileInput = screen.getByLabelText(/import/i)
    const content = '<opml/>'
    const file = new File([content], 'feeds.opml', { type: 'text/xml' })
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })
    vi.spyOn(file, 'text').mockResolvedValue(content)
    fireEvent.change(fileInput)
    await waitFor(() => expect(screen.getByText(/added 3/i)).toBeInTheDocument())
    expect(screen.getByText(/skipped 1/i)).toBeInTheDocument()
  })

  it('Export OPML button calls exportFeeds with opml format', async () => {
    render(<ImportExportBar onRefresh={onRefresh} />)
    fireEvent.click(screen.getByRole('button', { name: /export opml/i }))
    await waitFor(() => expect(api.exportFeeds).toHaveBeenCalledWith('opml'))
  })

  it('Export Markdown button calls exportFeeds with markdown format', async () => {
    render(<ImportExportBar onRefresh={onRefresh} />)
    fireEvent.click(screen.getByRole('button', { name: /export markdown/i }))
    await waitFor(() => expect(api.exportFeeds).toHaveBeenCalledWith('markdown'))
  })
})
