// Tests for the Settings page: engines (status, key storage, switches, addresses, defaults), the
// brief and vault groups with validation, the theme, and the error states.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import { resetFilingConfigured, setFilingConfigured } from '../../state/filingConfigured'
import SettingsPage from '../SettingsPage'
import type { EngineRow } from './api'
import { validateBrief, validateVault } from './validateSettings'
import { slugify } from './slug'

const api = vi.hoisted(() => ({
  loadEngines: vi.fn(),
  configureEngine: vi.fn(),
  removeEngine: vi.fn(),
  loadSettings: vi.fn(),
  patchSettings: vi.fn(),
  loadPrivacy: vi.fn(),
}))
vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./api')>()), ...api }))
// The bookmark button section asks the service for its key; this file is not about that.
vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  getImportButtonKey: vi.fn().mockResolvedValue({ key: '0123456789abcdef0123456789abcdef' }),
  rotateImportButtonKey: vi.fn(),
}))

const SECRET = 'sk-test-secret-1234567890'

function engine(over: Partial<EngineRow> & { id: string; label: string }): EngineRow {
  return {
    kind: 'api',
    available: true,
    reason: null,
    models: [
      { id: `${over.id}-a`, label: `${over.label} A` },
      { id: `${over.id}-b`, label: `${over.label} B` },
    ],
    default_model: `${over.id}-a`,
    enabled: true,
    needs_key: false,
    has_key: false,
    key_source: null,
    is_default: false,
    custom: false,
    base_url: null,
    ...over,
  }
}

function engines(): EngineRow[] {
  return [
    engine({ id: 'openrouter', label: 'OpenRouter', needs_key: true, has_key: true, key_source: 'keyring', is_default: true }),
    engine({ id: 'openai', label: 'OpenAI', available: false, reason: 'No API key saved.', needs_key: true, models: [] }),
    engine({ id: 'anthropic', label: 'Anthropic', needs_key: true, has_key: true, key_source: 'env' }),
    engine({ id: 'claude_code', label: 'Claude Code', kind: 'cli', available: false, reason: 'Switched off', enabled: false, models: [] }),
    engine({ id: 'lmstudio', label: 'LM Studio', kind: 'local', available: false, reason: 'No local server is running.', models: [], base_url: 'http://localhost:1234/v1' }),
    engine({ id: 'custom-lab', label: 'Lab server', kind: 'custom', custom: true, base_url: 'http://10.0.0.5:8000/v1' }),
  ]
}

const settings = { vault_path: 'C:/Vault', radar_brief_time: '06:30', radar_timezone: '', radar_collect_hours: 2, assist_default_engine: 'openrouter', assist_default_model: 'openrouter-a' }

beforeEach(() => {
  vi.clearAllMocks()
  document.documentElement.removeAttribute('data-theme')
  window.localStorage.clear()
  // Most of these tests are about an install where filing is set up; one below turns it off.
  setFilingConfigured(true)
  api.loadEngines.mockResolvedValue(engines())
  api.loadSettings.mockResolvedValue(settings)
  api.loadPrivacy.mockResolvedValue(null)
  api.patchSettings.mockImplementation(async (change: Record<string, unknown>) => ({ ...settings, ...change }))
  api.configureEngine.mockImplementation(async (id: string, change: Record<string, unknown>) => ({ ...engines().find((e) => e.id === id), ...change }))
})

afterEach(() => {
  document.documentElement.removeAttribute('data-theme')
  resetFilingConfigured()
})

describe('AI engines', () => {
  it('lists every engine with its status in words and the reason when it is not usable', async () => {
    render(<SettingsPage />)
    expect(await screen.findByText('OpenAI')).toBeInTheDocument()
    expect(screen.getByText('No API key saved.')).toBeInTheDocument()
    expect(screen.getByText('No local server is running.')).toBeInTheDocument()
    expect(screen.getAllByText('Available').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('Not configured').length).toBe(3)
    expect(screen.getByText('Key stored')).toBeInTheDocument()
    expect(screen.getByText(/read from this computer's environment/)).toBeInTheDocument()
    expect(screen.getByText(/Uses the program and sign-in already on this computer, for your personal use only/)).toBeInTheDocument()
  })

  it('sends a pasted key once and never shows it again', async () => {
    render(<SettingsPage />)
    const field = await screen.findByLabelText('API key for OpenAI')
    expect(field).toHaveAttribute('type', 'password')
    fireEvent.change(field, { target: { value: SECRET } })
    fireEvent.click(screen.getByRole('button', { name: 'Save key' }))
    await waitFor(() => expect(api.configureEngine).toHaveBeenCalledWith('openai', { api_key: SECRET }))
    const row = screen.getByText('OpenAI', { selector: '.rst-name' }).closest('li') as HTMLElement
    expect(await within(row).findByText('Key stored', { selector: 'span.rst-ok' })).toBeInTheDocument()
    expect(screen.queryByLabelText('API key for OpenAI')).not.toBeInTheDocument()
    expect(document.body.innerHTML).not.toContain(SECRET)
    expect(screen.queryByDisplayValue(SECRET)).not.toBeInTheDocument()
  })

  it('does not leave a key in the field when storing it fails', async () => {
    api.configureEngine.mockRejectedValueOnce(new ApiError('The operating system key store is not available.', { status: 503, kind: 'http', path: '/engines/openai' }))
    render(<SettingsPage />)
    const field = await screen.findByLabelText('API key for OpenAI')
    fireEvent.change(field, { target: { value: SECRET } })
    fireEvent.click(screen.getByRole('button', { name: 'Save key' }))
    expect(await screen.findByText('The operating system key store is not available.')).toBeInTheDocument()
    expect(screen.getByLabelText('API key for OpenAI')).toHaveValue('')
    expect(document.body.innerHTML).not.toContain(SECRET)
  })

  it('switches a command-line engine on', async () => {
    render(<SettingsPage />)
    fireEvent.click(await screen.findByRole('switch', { name: 'Use Claude Code' }))
    await waitFor(() => expect(api.configureEngine).toHaveBeenCalledWith('claude_code', { enabled: true }))
    expect(await screen.findByText('Switched on.')).toBeInTheDocument()
  })

  it('saves a local server address and refuses a malformed one', async () => {
    render(<SettingsPage />)
    const address = await screen.findByLabelText('Server address for LM Studio')
    fireEvent.change(address, { target: { value: 'localhost:1234' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Save address' })[0])
    expect(await screen.findByText('The address must start with http:// or https://')).toBeInTheDocument()
    expect(api.configureEngine).not.toHaveBeenCalled()
    fireEvent.change(address, { target: { value: 'http://localhost:5000/v1' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Save address' })[0])
    await waitFor(() => expect(api.configureEngine).toHaveBeenCalledWith('lmstudio', { base_url: 'http://localhost:5000/v1' }))
  })

  it('adds a custom server and removes one after a second click', async () => {
    render(<SettingsPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add a custom server' }))
    fireEvent.change(screen.getByLabelText('Server name'), { target: { value: 'Office Box' } })
    fireEvent.change(screen.getByLabelText('Server address'), { target: { value: 'http://10.0.0.9:8000/v1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add server' }))
    await waitFor(() => expect(api.configureEngine).toHaveBeenCalledWith('custom-office-box', { base_url: 'http://10.0.0.9:8000/v1', label: 'Office Box' }))

    api.removeEngine.mockResolvedValue(null)
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove this server' })[0])
    expect(api.removeEngine).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /Click again to remove/ }))
    await waitFor(() => expect(api.removeEngine).toHaveBeenCalledWith('custom-lab'))
  })

  it('saves the default engine and model through the settings', async () => {
    render(<SettingsPage />)
    fireEvent.change(await screen.findByLabelText('Default engine'), { target: { value: 'anthropic' } })
    expect(screen.getByLabelText('Default model')).toHaveValue('anthropic-a')
    fireEvent.change(screen.getByLabelText('Default model'), { target: { value: 'anthropic-b' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save default' }))
    await waitFor(() => expect(api.patchSettings).toHaveBeenCalledWith({ assist_default_engine: 'anthropic', assist_default_model: 'anthropic-b' }))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('warns when the service does not report the default back', async () => {
    api.patchSettings.mockResolvedValue({ vault_path: 'C:/Vault' })
    render(<SettingsPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Save default' }))
    expect(await screen.findByText(/did not confirm the new default/)).toBeInTheDocument()
  })

  it('shows an error and a retry when the engines cannot be loaded', async () => {
    api.loadEngines.mockRejectedValueOnce(new ApiError('Spyglass is not reachable. Check that the service is running, then try again.', { status: 0, kind: 'network', path: '/engines' }))
    render(<SettingsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Spyglass is not reachable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('OpenRouter', { selector: '.rst-name' })).toBeInTheDocument()
  })
})

describe('Daily brief and Vault', () => {
  it('saves the brief schedule', async () => {
    render(<SettingsPage />)
    const time = await screen.findByLabelText('Brief time')
    expect(time).toHaveValue('06:30')
    fireEvent.change(time, { target: { value: '07:15' } })
    fireEvent.change(screen.getByLabelText('Collect every (hours)'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save brief settings' }))
    await waitFor(() => expect(api.patchSettings).toHaveBeenCalledWith({ radar_brief_time: '07:15', radar_timezone: '', radar_collect_hours: 3 }))
    expect(await screen.findByText(/Close and start Spyglass again for the new times to apply/)).toBeInTheDocument()
  })

  it('explains what is wrong and does not save an invalid schedule', async () => {
    render(<SettingsPage />)
    fireEvent.change(await screen.findByLabelText('Time zone'), { target: { value: 'Mars/Base' } })
    fireEvent.change(screen.getByLabelText('Collect every (hours)'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save brief settings' }))
    expect(await screen.findByText(/Use a time zone name like Europe\/Amsterdam/)).toBeInTheDocument()
    expect(screen.getByText(/Enter a number of hours from 0.25 to 24/)).toBeInTheDocument()
    expect(api.patchSettings).not.toHaveBeenCalled()
  })

  it('has no folder-for-saved-notes field, and explains the queue in three plain sentences', async () => {
    render(<SettingsPage />)
    expect(await screen.findByLabelText('Vault folder')).toHaveValue('C:/Vault')
    expect(screen.queryByLabelText('Folder for saved notes')).not.toBeInTheDocument()
    expect(screen.getByText(/Spyglass never writes into the vault itself\. File in vault adds an item to a queue\. File now opens one Claude Code session in the vault, where your own vault skills file the items after your yes\./)).toBeInTheDocument()
  })

  it('where filing is not set up, explains it in one place and leaves the queue out of the Vault group', async () => {
    setFilingConfigured(false)
    render(<SettingsPage />)
    expect(await screen.findByLabelText('Vault folder')).toHaveValue('C:/Vault')
    expect(screen.getByText(/Filing into a notes vault is an optional integration\./)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Off/)).not.toBeInTheDocument()
    expect(screen.queryByText(/File in vault adds an item to a queue/)).not.toBeInTheDocument()
    expect(screen.getByText('Spyglass never writes into the vault itself.')).toBeInTheDocument()
  })

  it('saves the vault folder alone and reports a failure in words', async () => {
    render(<SettingsPage />)
    fireEvent.change(await screen.findByLabelText('Vault folder'), { target: { value: 'D:/Notes' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save vault settings' }))
    await waitFor(() => expect(api.patchSettings).toHaveBeenCalledWith({ vault_path: 'D:/Notes' }))
    expect(await screen.findByText('Saved.', { selector: '.rst-ok' })).toBeInTheDocument()

    api.patchSettings.mockRejectedValueOnce(new ApiError('Spyglass hit an error while doing this. Try again; if it repeats, check the service log.', { status: 500, kind: 'http', path: '/api/settings' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save vault settings' }))
    expect(await screen.findByText(/Spyglass hit an error/)).toBeInTheDocument()
  })

  it('does not save an empty vault folder', async () => {
    render(<SettingsPage />)
    fireEvent.change(await screen.findByLabelText('Vault folder'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save vault settings' }))
    expect(await screen.findByText('Enter the folder your vault lives in.')).toBeInTheDocument()
    expect(api.patchSettings).not.toHaveBeenCalled()
  })

  it('shows an error with a retry when the settings cannot be loaded', async () => {
    api.loadSettings.mockRejectedValueOnce(new ApiError('Spyglass is not reachable. Check that the service is running, then try again.', { status: 0, kind: 'network', path: '/api/settings' }))
    render(<SettingsPage />)
    const alert = await screen.findByRole('alert')
    fireEvent.click(within(alert.parentElement as HTMLElement).getByRole('button', { name: 'Try again' }))
    expect(await screen.findByLabelText('Brief time')).toBeInTheDocument()
  })
})

describe('Appearance', () => {
  it('switches the theme through the app theme mechanism', async () => {
    render(<SettingsPage />)
    fireEvent.click(await screen.findByLabelText('Dark'))
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    fireEvent.click(screen.getByLabelText('Follow system'))
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })
})

describe('helpers', () => {
  it('validates the brief fields', () => {
    expect(validateBrief({ time: '06:30', zone: '', hours: '2' }, [])).toEqual({})
    expect(validateBrief({ time: '25:00', zone: 'x', hours: 'abc' }, ['Europe/Amsterdam'])).toHaveProperty('time')
    expect(validateBrief({ time: '06:30', zone: 'Europe/Amsterdam', hours: '30' }, ['Europe/Amsterdam']).hours).toBeDefined()
  })

  it('validates the vault folder', () => {
    expect(validateVault({ vault: 'C:/Vault' })).toEqual({})
    expect(validateVault({ vault: '  ' }).vault).toBeDefined()
  })

  it('makes a safe id from a server name', () => {
    expect(slugify('  Office Box #2 ')).toBe('office-box-2')
    expect(slugify('***')).toBe('')
  })
})
