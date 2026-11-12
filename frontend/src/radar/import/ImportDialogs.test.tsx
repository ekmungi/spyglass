// Tests for the two extra doors of the Add link dialog: "Paste the text" and "Add a file".
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RadarItem } from '../api/types'
import { AddLinkDialog } from '../shell/AddLinkDialog'
import { FileDialog } from './FileDialog'
import { fileProblem, MAX_FILE_BYTES } from './messages'
import { PasteTextDialog } from './PasteTextDialog'

const api = vi.hoisted(() => ({ importText: vi.fn(), importFile: vi.fn(), captureLink: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

const URL = 'https://news.example.com/story'
const item = { id: 77, title: 'A story', headline: 'A story', origin: 'news.example.com' } as RadarItem

function fileOf(name: string, size = 10): File {
  const file = new File(['x'.repeat(Math.min(size, 10))], name)
  Object.defineProperty(file, 'size', { value: size })
  return file
}

beforeEach(() => {
  vi.clearAllMocks()
  api.importText.mockResolvedValue(item)
  api.importFile.mockResolvedValue(item)
})

describe('PasteTextDialog', () => {
  const props = () => ({ open: true, onClose: vi.fn(), onBack: vi.fn(), onAdded: vi.fn() })

  it('sends the address and the text, and reports the added item', async () => {
    const p = props()
    render(<PasteTextDialog {...p} />)
    fireEvent.change(screen.getByLabelText('Web address of the article'), { target: { value: ` ${URL} ` } })
    fireEvent.change(screen.getByLabelText('The article’s text'), { target: { value: 'Headline\n\nThe body.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add the text' }))
    await waitFor(() => expect(p.onAdded).toHaveBeenCalledWith(item, URL))
    expect(api.importText).toHaveBeenCalledWith({ url: URL, text: 'Headline\n\nThe body.' })
  })

  it('asks for a web address and for text before sending', () => {
    render(<PasteTextDialog {...props()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add the text' }))
    expect(screen.getByRole('alert')).toHaveTextContent('full web address')
    fireEvent.change(screen.getByLabelText('Web address of the article'), { target: { value: URL } })
    fireEvent.click(screen.getByRole('button', { name: 'Add the text' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Paste the text')
    expect(api.importText).not.toHaveBeenCalled()
  })

  it('shows the service refusal', async () => {
    api.importText.mockRejectedValue(new Error('Links to this computer or a private network are not accepted.'))
    render(<PasteTextDialog {...props()} />)
    fireEvent.change(screen.getByLabelText('Web address of the article'), { target: { value: URL } })
    fireEvent.change(screen.getByLabelText('The article’s text'), { target: { value: 'Text' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add the text' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('private network')
  })

  it('goes back to the link form', () => {
    const p = props()
    render(<PasteTextDialog {...p} />)
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(p.onBack).toHaveBeenCalled()
  })
})

describe('FileDialog', () => {
  const props = () => ({ open: true, onClose: vi.fn(), onBack: vi.fn(), onAdded: vi.fn() })

  it('uploads the chosen file with its address', async () => {
    const p = props()
    render(<FileDialog {...p} />)
    const file = fileOf('paper.pdf')
    fireEvent.change(screen.getByLabelText('Web address of the page'), { target: { value: URL } })
    fireEvent.change(screen.getByLabelText('File'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Add the file' }))
    await waitFor(() => expect(p.onAdded).toHaveBeenCalledWith(item, URL))
    expect(api.importFile).toHaveBeenCalledWith(URL, file)
  })

  it('refuses a missing, unsupported or oversized file before uploading', () => {
    render(<FileDialog {...props()} />)
    fireEvent.change(screen.getByLabelText('Web address of the page'), { target: { value: URL } })
    fireEvent.click(screen.getByRole('button', { name: 'Add the file' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a file')
    fireEvent.change(screen.getByLabelText('File'), { target: { files: [fileOf('notes.docx')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Add the file' }))
    expect(screen.getByRole('alert')).toHaveTextContent('.pdf, .html or .mhtml')
    expect(api.importFile).not.toHaveBeenCalled()
  })

  it('knows the file rules', () => {
    expect(fileProblem(fileOf('page.MHTML'))).toBeNull()
    expect(fileProblem(fileOf('page.htm'))).toBeNull()
    expect(fileProblem(fileOf('big.pdf', MAX_FILE_BYTES + 1))).toMatch('150 MB')
    expect(MAX_FILE_BYTES).toBe(150 * 1024 * 1024)
    expect(fileProblem(fileOf('empty.html', 0))).toMatch('empty')
  })
})

describe('AddLinkDialog doors', () => {
  it('keeps the link form first and opens the paste door from a quiet link', async () => {
    render(<AddLinkDialog open onClose={() => undefined} />)
    expect(screen.getByRole('dialog', { name: 'Add a link' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Paste the text' }))
    expect(screen.getByRole('dialog', { name: 'Paste the text' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Web address of the article'), { target: { value: URL } })
    fireEvent.change(screen.getByLabelText('The article’s text'), { target: { value: 'Some text' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add the text' }))
    expect(await screen.findByRole('dialog', { name: 'Page added' })).toBeInTheDocument()
  })

  it('opens the file door and comes back', () => {
    render(<AddLinkDialog open onClose={() => undefined} />)
    fireEvent.click(screen.getByRole('button', { name: 'add a saved file' }))
    expect(screen.getByRole('dialog', { name: 'Add a file' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByRole('dialog', { name: 'Add a link' })).toBeInTheDocument()
  })
})
