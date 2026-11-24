// Tests for the first-start page: the data folder and vault form, the restart wait, and the
// browser extension guide.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import type { FirstStart } from '../../api/types'
import { WelcomePage } from './WelcomePage'

const api = vi.hoisted(() => ({
  saveFirstStart: vi.fn(),
  dismissSetupGuide: vi.fn(),
  openExtensionsPage: vi.fn(),
  getExtensionFolder: vi.fn(),
}))
const wait = vi.hoisted(() => ({ waitForService: vi.fn() }))
const toasts = vi.hoisted(() => vi.fn())
vi.mock('../../api/client', async (original) => ({ ...(await original<typeof import('../../api/client')>()), ...api }))
vi.mock('../../api/waitForService', () => wait)
vi.mock('../../ui', async (original) => ({ ...(await original<typeof import('../../ui')>()), toast: toasts }))

const FRESH: FirstStart = { needed: true, data_dir: 'C:\\Users\\me\\AppData\\Local\\Spyglass\\data', vault_path: null, browsers: [] }
const WITH_BROWSERS: FirstStart = {
  ...FRESH,
  browsers: [
    { id: 'chrome', name: 'Chrome' },
    { id: 'edge', name: 'Edge' },
  ],
}
const GUIDE_ONLY: FirstStart = { ...WITH_BROWSERS, needed: false }

beforeEach(() => {
  vi.clearAllMocks()
  api.saveFirstStart.mockResolvedValue({ restart: false, data_dir: FRESH.data_dir })
  api.dismissSetupGuide.mockResolvedValue(null)
  api.openExtensionsPage.mockResolvedValue(null)
  api.getExtensionFolder.mockResolvedValue({ folder: 'C:\\Spyglass\\browser-extension' })
  wait.waitForService.mockResolvedValue(true)
})

afterEach(() => cleanup())

const folderField = () => screen.getByLabelText('Data folder') as HTMLInputElement
const vaultField = () => screen.getByLabelText('Obsidian vault (optional)') as HTMLInputElement
const save = () => screen.getByRole('button', { name: 'Save and continue' })
const openButton = (name: string) => screen.getByRole('button', { name: `Open ${name}\u2019s extensions page` })

describe('WelcomePage data section', () => {
  it('prefills the data folder and leaves the vault empty', () => {
    render(<WelcomePage firstStart={FRESH} onDone={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Welcome to Spyglass' })).toBeInTheDocument()
    expect(folderField().value).toBe(FRESH.data_dir)
    expect(vaultField().value).toBe('')
    expect(screen.getByText(/stays when Spyglass is uninstalled/)).toBeInTheDocument()
  })

  it('prefills a vault that is already chosen', () => {
    render(<WelcomePage firstStart={{ ...FRESH, vault_path: 'D:\\Vault' }} onDone={vi.fn()} />)
    expect(vaultField().value).toBe('D:\\Vault')
  })

  it('saves the trimmed values, sends null for an empty vault, and finishes when no restart is needed', async () => {
    const onDone = vi.fn()
    render(<WelcomePage firstStart={FRESH} onDone={onDone} />)
    fireEvent.change(folderField(), { target: { value: '  D:\\Spy  ' } })
    fireEvent.change(vaultField(), { target: { value: '   ' } })
    fireEvent.click(save())
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(api.saveFirstStart).toHaveBeenCalledWith({ data_dir: 'D:\\Spy', vault_path: null })
  })

  it('sends a typed vault path trimmed', async () => {
    render(<WelcomePage firstStart={FRESH} onDone={vi.fn()} />)
    fireEvent.change(vaultField(), { target: { value: ' D:\\Vault ' } })
    fireEvent.click(save())
    await waitFor(() => expect(api.saveFirstStart).toHaveBeenCalledWith({ data_dir: FRESH.data_dir, vault_path: 'D:\\Vault' }))
  })

  it('shows the sentence of a refused choice and changes nothing else', async () => {
    api.saveFirstStart.mockRejectedValue(new ApiError('That folder is not writable.', { status: 400, kind: 'http', path: '/x' }))
    const onDone = vi.fn()
    render(<WelcomePage firstStart={FRESH} onDone={onDone} />)
    fireEvent.click(save())
    expect(await screen.findByRole('alert')).toHaveTextContent('That folder is not writable.')
    expect(folderField().value).toBe(FRESH.data_dir)
    expect(save()).toBeEnabled()
    expect(onDone).not.toHaveBeenCalled()
  })

  it('disables the button while saving', async () => {
    let finish: (value: unknown) => void = () => {}
    api.saveFirstStart.mockReturnValue(new Promise((resolve) => (finish = resolve)))
    render(<WelcomePage firstStart={FRESH} onDone={vi.fn()} />)
    fireEvent.click(save())
    await waitFor(() => expect(save()).toBeDisabled())
    finish({ restart: false, data_dir: FRESH.data_dir })
  })
})

describe('WelcomePage restart', () => {
  beforeEach(() => api.saveFirstStart.mockResolvedValue({ restart: true, data_dir: 'D:\\Spy' }))

  it('replaces the form with a status line, waits for the service and reloads', async () => {
    const reload = vi.fn()
    render(<WelcomePage firstStart={FRESH} onDone={vi.fn()} reload={reload} />)
    fireEvent.click(save())
    expect(await screen.findByRole('status')).toHaveTextContent('Spyglass is starting again on the new folder. This page reloads when it is ready.')
    expect(screen.queryByLabelText('Data folder')).toBeNull()
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
    expect(wait.waitForService).toHaveBeenCalledWith({ afterStop: true })
  })

  it('says so and points to the Start menu when the service does not come back', async () => {
    wait.waitForService.mockResolvedValue(false)
    const reload = vi.fn()
    render(<WelcomePage firstStart={FRESH} onDone={vi.fn()} reload={reload} />)
    fireEvent.click(save())
    expect(await screen.findByText(/did not start again within a minute/)).toHaveTextContent(/Start menu/)
    expect(reload).not.toHaveBeenCalled()
  })
})

describe('WelcomePage browser guide', () => {
  it('goes to the guide after a save that needs no restart', async () => {
    render(<WelcomePage firstStart={WITH_BROWSERS} onDone={vi.fn()} />)
    fireEvent.click(save())
    expect((await screen.findAllByText(/Load unpacked/)).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('Data folder')).toBeNull()
    expect(await screen.findByText('C:\\Spyglass\\browser-extension')).toBeInTheDocument()
    expect(openButton('Chrome')).toBeInTheDocument()
    expect(openButton('Edge')).toBeInTheDocument()
  })

  it('opens straight on the guide when no first start is needed', () => {
    render(<WelcomePage firstStart={GUIDE_ONLY} onDone={vi.fn()} />)
    expect(screen.queryByLabelText('Data folder')).toBeNull()
    expect(screen.getAllByText(/Load unpacked/).length).toBeGreaterThan(0)
  })

  it('opens the extensions page of the browser whose button is pressed', async () => {
    render(<WelcomePage firstStart={GUIDE_ONLY} onDone={vi.fn()} />)
    fireEvent.click(openButton('Edge'))
    await waitFor(() => expect(api.openExtensionsPage).toHaveBeenCalledWith('edge'))
  })

  it('shows a toast when a browser cannot be opened', async () => {
    api.openExtensionsPage.mockRejectedValue(new ApiError('That browser is not installed.', { status: 404, kind: 'http', path: '/x' }))
    render(<WelcomePage firstStart={GUIDE_ONLY} onDone={vi.fn()} />)
    fireEvent.click(openButton('Chrome'))
    await waitFor(() => expect(toasts).toHaveBeenCalledWith('That browser is not installed.', { tone: 'error' }))
  })

  it.each(['Done', 'Skip for now'])('%s forgets the guide and finishes', async (label) => {
    const onDone = vi.fn()
    render(<WelcomePage firstStart={GUIDE_ONLY} onDone={onDone} />)
    fireEvent.click(screen.getByRole('button', { name: label }))
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(api.dismissSetupGuide).toHaveBeenCalledTimes(1)
  })

  it('still finishes, with a toast, when forgetting the guide fails', async () => {
    api.dismissSetupGuide.mockRejectedValue(new Error('offline'))
    const onDone = vi.fn()
    render(<WelcomePage firstStart={GUIDE_ONLY} onDone={onDone} />)
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(toasts).toHaveBeenCalledWith(expect.stringContaining('offline'), { tone: 'error' })
  })
})
