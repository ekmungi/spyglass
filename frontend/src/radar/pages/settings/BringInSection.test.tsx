// Tests for the Settings section that offers the Send to Spyglass bookmark button.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { BringInSection } from './BringInSection'

const api = vi.hoisted(() => ({
  getImportButtonKey: vi.fn(),
  rotateImportButtonKey: vi.fn(),
}))
vi.mock('../../api/client', async (original) => ({ ...(await original<typeof import('../../api/client')>()), ...api }))

const KEY = '0123456789abcdef0123456789abcdef'
const NEW_KEY = 'fedcba9876543210fedcba9876543210'

/** The decoded script of the button once it has been built. */
async function builtScript(): Promise<string> {
  const link = (await screen.findByText('Send to Spyglass')).closest('a') as HTMLAnchorElement
  await waitFor(() => expect(link.getAttribute('href')).toBeTruthy())
  return decodeURIComponent(link.getAttribute('href') ?? '')
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getImportButtonKey.mockResolvedValue({ key: KEY })
  api.rotateImportButtonKey.mockResolvedValue({ key: NEW_KEY })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('BringInSection', () => {
  it('puts the browser extension first, with the bookmark button below it under its own heading', async () => {
    render(<BringInSection origin="http://localhost:7778" />)
    const headings = screen.getAllByRole('heading').map((heading) => heading.textContent)
    expect(headings.indexOf('Browser extension (recommended)')).toBeGreaterThanOrEqual(0)
    expect(headings.indexOf('Browser extension (recommended)')).toBeLessThan(headings.indexOf('Without installing anything'))
    expect(screen.getByText(/Install the Send to Spyglass extension once/)).toBeInTheDocument()
    expect(screen.getByText(/It only acts when you click, and it talks only to Spyglass on this computer/)).toBeInTheDocument()
    expect(screen.getByText('browser-extension')).toBeInTheDocument()
    await screen.findByText('Send to Spyglass')
  })

  it('shows the extension key masked, and reveals and copies it on request', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<BringInSection origin="http://localhost:7778" />)
    await screen.findByRole('button', { name: 'Show' })
    expect(screen.queryByText(KEY)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Show' }))
    expect(screen.getByText(KEY)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Hide' }))
    expect(screen.queryByText(KEY)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(writeText).toHaveBeenCalledWith(KEY)
    expect(api.getImportButtonKey).toHaveBeenCalledTimes(1)
  })

  it('says that a new button also disconnects the extension, and shows the new key masked', async () => {
    render(<BringInSection origin="http://localhost:7778" />)
    expect(screen.getByText(/also replaces this key, which disconnects the extension/)).toBeInTheDocument()
    await screen.findByRole('button', { name: 'Show' })
    fireEvent.click(screen.getByRole('button', { name: 'Make a new button' }))
    expect(await screen.findByText(/Paste the new key into the extension/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show' }))
    expect(screen.getByText(NEW_KEY)).toBeInTheDocument()
    expect(screen.queryByText(KEY)).toBeNull()
  })

  it('says why the key is missing instead of showing a key it could not read', async () => {
    api.getImportButtonKey.mockRejectedValueOnce(new Error('cross-site request refused'))
    render(<BringInSection origin="http://localhost:7778" />)
    expect(await screen.findByText(/The key could not be read: cross-site request refused/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Copy' })).toBeNull()
  })

  it('offers a draggable button that points at this copy of Spyglass and carries its key', async () => {
    render(<BringInSection origin="http://localhost:7778" />)
    expect(screen.getByRole('heading', { name: 'Without installing anything' })).toBeInTheDocument()
    const link = (await screen.findByText('Send to Spyglass')).closest('a') as HTMLAnchorElement
    const script = await builtScript()
    expect(script.startsWith('javascript:')).toBe(true)
    expect(script).toContain("'http://localhost:7778'")
    expect(script).toContain(`'${KEY}'`)
    expect(link.getAttribute('draggable')).toBe('true')
    expect(api.getImportButtonKey).toHaveBeenCalledTimes(1)
  })

  it('explains in plain sentences how to use it, and what to do when a site blocks it', async () => {
    render(<BringInSection origin="http://localhost:7778" />)
    expect(screen.getByText(/Drag the button below to your browser.s bookmarks bar/)).toBeInTheDocument()
    expect(screen.getByText(/nothing is added until you press Add to Spyglass/)).toBeInTheDocument()
    expect(screen.getByText(/Some sites block the button/)).toBeInTheDocument()
    await screen.findByText('Send to Spyglass')
  })

  it('does nothing when clicked inside Spyglass except say where it belongs', async () => {
    render(<BringInSection origin="http://localhost:7778" />)
    const link = await screen.findByText('Send to Spyglass')
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    fireEvent(link, event)
    expect(event.defaultPrevented).toBe(true)
    expect(screen.getByRole('status')).toHaveTextContent('Drag the button to your bookmarks bar')
  })

  it('refuses to build a button for an unusual address, and never asks for the key', () => {
    render(<BringInSection origin="null" />)
    expect(screen.queryByText('Send to Spyglass')).toBeNull()
    expect(screen.getByText(/cannot be made for this address/)).toBeInTheDocument()
    expect(api.getImportButtonKey).not.toHaveBeenCalled()
  })

  it('says so, and offers no button, when the key cannot be read or is malformed', async () => {
    api.getImportButtonKey.mockRejectedValueOnce(new Error('cross-site request refused'))
    const { unmount } = render(<BringInSection origin="http://localhost:7778" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('cross-site request refused')
    expect(screen.queryByText('Send to Spyglass')).toBeNull()
    unmount()
    api.getImportButtonKey.mockResolvedValueOnce({ key: 'not-a-key' })
    render(<BringInSection origin="http://localhost:7778" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('unexpected answer')
    expect(screen.queryByText('Send to Spyglass')).toBeNull()
  })

  it('makes a new button on request: the new key replaces the old and the reader is told the old one stops working', async () => {
    render(<BringInSection origin="http://localhost:7778" />)
    expect(await builtScript()).toContain(`'${KEY}'`)
    fireEvent.click(screen.getByRole('button', { name: 'Make a new button' }))
    await waitFor(() => expect(api.rotateImportButtonKey).toHaveBeenCalledTimes(1))
    await waitFor(async () => expect(await builtScript()).toContain(`'${NEW_KEY}'`))
    expect(await builtScript()).not.toContain(KEY)
    expect(screen.getByText(/in place of the old one, which no longer works/)).toBeInTheDocument()
  })

  it('keeps the old button and shows the problem when making a new one fails', async () => {
    api.rotateImportButtonKey.mockRejectedValueOnce(new Error('could not save the key'))
    render(<BringInSection origin="http://localhost:7778" />)
    await builtScript()
    fireEvent.click(screen.getByRole('button', { name: 'Make a new button' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('could not save the key')
    expect(screen.queryByText(/which no longer works/)).toBeNull()
  })

  it('scrolls itself into view when the reader arrives from the hint', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    render(<BringInSection origin="http://localhost:7778" focus />)
    expect(scroll).toHaveBeenCalled()
    await screen.findByText('Send to Spyglass')
  })
})
