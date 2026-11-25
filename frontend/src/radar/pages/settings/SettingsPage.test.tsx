// Tests for the Settings page: engines (status, key storage, switches, addresses, defaults), the
// brief and vault groups with validation, the theme, and the error states.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import * as client from '../../api/client'
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
  // The extension and this-computer sections ask the desktop app about itself; this file is not about that.
  getBrowsers: vi.fn().mockResolvedValue([]),
  getExtensionFolder: vi.fn().mockRejectedValue(new Error('not the desktop app')),
  getAutostart: vi.fn().mockResolvedValue({ available: false, enabled: false }),
  // The "Parts not installed" note asks which optional parts are missing; most tests have none missing.
  getCapabilities: vi.fn().mockResolvedValue({ pdf_reading: 'full', local_ai: true, missing: [] }),
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


/** Choose a tab of the Settings strip by its visible name. */
function openTab(name: string) {
  fireEvent.click(screen.getByRole('tab', { name }))
}

/** Press the button that lists the engines that are not set up (the list shows only the set-up ones at first). */
async function showEveryEngine() {
  fireEvent.click(await screen.findByRole('button', { name: /engines? that (is|are) not set up/ }))
}

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
  it('lists every engine, once all are shown, with its status in words and the reason when it is not usable', async () => {
    render(<SettingsPage />)
    openTab('AI engines')
    await showEveryEngine()
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
    openTab('AI engines')
    await showEveryEngine()
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
    openTab('AI engines')
    await showEveryEngine()
    const field = await screen.findByLabelText('API key for OpenAI')
    fireEvent.change(field, { target: { value: SECRET } })
    fireEvent.click(screen.getByRole('button', { name: 'Save key' }))
    expect(await screen.findByText('The operating system key store is not available.')).toBeInTheDocument()
    expect(screen.getByLabelText('API key for OpenAI')).toHaveValue('')
    expect(document.body.innerHTML).not.toContain(SECRET)
  })

  it('switches a command-line engine on', async () => {
    render(<SettingsPage />)
    openTab('AI engines')
    await showEveryEngine()
    fireEvent.click(await screen.findByRole('switch', { name: 'Use Claude Code' }))
    await waitFor(() => expect(api.configureEngine).toHaveBeenCalledWith('claude_code', { enabled: true }))
    expect(await screen.findByText('Switched on.')).toBeInTheDocument()
  })

  it('saves a local server address and refuses a malformed one', async () => {
    render(<SettingsPage />)
    openTab('AI engines')
    await showEveryEngine()
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
    openTab('AI engines')
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
    openTab('AI engines')
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
    openTab('AI engines')
    fireEvent.click(await screen.findByRole('button', { name: 'Save default' }))
    expect(await screen.findByText(/did not confirm the new default/)).toBeInTheDocument()
  })

  it('shows an error and a retry when the engines cannot be loaded', async () => {
    api.loadEngines.mockRejectedValueOnce(new ApiError('Spyglass is not reachable. Check that the service is running, then try again.', { status: 0, kind: 'network', path: '/engines' }))
    render(<SettingsPage />)
    openTab('AI engines')
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
    openTab('Vault and filing')
    expect(await screen.findByLabelText('Vault folder')).toHaveValue('C:/Vault')
    expect(screen.queryByLabelText('Folder for saved notes')).not.toBeInTheDocument()
    expect(screen.getByText(/Spyglass never writes into the vault itself\. File in vault adds an item to a queue\. File now opens one Claude Code session in the vault, where your own vault skills file the items after your yes\./)).toBeInTheDocument()
  })

  it('where filing is not set up, explains it in one place and leaves the queue out of the Vault group', async () => {
    setFilingConfigured(false)
    render(<SettingsPage />)
    openTab('Vault and filing')
    expect(await screen.findByLabelText('Vault folder')).toHaveValue('C:/Vault')
    expect(screen.getByText(/Filing into a notes vault is an optional integration\./)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Off/)).not.toBeInTheDocument()
    expect(screen.queryByText(/File in vault adds an item to a queue/)).not.toBeInTheDocument()
    expect(screen.getByText('Spyglass never writes into the vault itself.')).toBeInTheDocument()
  })

  it('saves the vault folder alone and reports a failure in words', async () => {
    render(<SettingsPage />)
    openTab('Vault and filing')
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
    openTab('Vault and filing')
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
    openTab('Appearance')
    fireEvent.click(await screen.findByLabelText('Dark'))
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    fireEvent.click(screen.getByLabelText('Follow system'))
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })
})

/** The ids of the parts that are on screen (not in a hidden part), without the "settings-" start, in page order. */
function partsOnScreen(): string[] {
  return Array.from(document.querySelectorAll('[id^="settings-"]'))
    .filter((heading) => !heading.closest('[hidden]'))
    .map((heading) => heading.id.replace('settings-', ''))
}

/** The part with this heading id, whether or not it is hidden; null when it is not in the document at all. */
const partNamed = (name: string) => document.getElementById(`settings-${name}`)

describe('Settings tabs', () => {
  afterEach(() => {
    window.location.hash = ''
    // Back to "no part is missing", which the other tests rely on.
    vi.mocked(client.getCapabilities).mockResolvedValue({ pdf_reading: 'full', local_ai: true, missing: [] })
  })

  it('has the six tabs in order, with General selected and the page in its wide width', () => {
    const { container } = render(<SettingsPage />)
    const strip = screen.getByRole('tablist', { name: 'Settings' })
    expect(within(strip).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'General',
      'AI engines',
      'Appearance',
      'Bringing things in',
      'Vault and filing',
      'Privacy and usage',
    ])
    expect(screen.getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
    expect(container.firstElementChild).toHaveClass('r-page', 'r-page--wide')
  })

  it('shows on each tab exactly its own parts', async () => {
    vi.mocked(client.getCapabilities).mockResolvedValue({ pdf_reading: 'basic', local_ai: false, missing: [{ id: 'pdf', name: 'PDF reading', effect: 'PDF reading is basic.', how_to_add: 'Modify the install.' }] })
    render(<SettingsPage />)
    await waitFor(() => expect(partsOnScreen()).toEqual(['brief', 'desktop', 'parts']))
    const expected: Array<[string, string[]]> = [
      ['AI engines', ['engines']],
      ['Appearance', ['appearance']],
      ['Bringing things in', ['extension', 'bring-in']],
      ['Vault and filing', ['vault', 'filing']],
      ['Privacy and usage', ['privacy', 'usage']],
    ]
    for (const [tab, parts] of expected) {
      openTab(tab)
      expect(partsOnScreen()).toEqual(parts)
    }
    // Coming back asks the service again which parts are missing, so the note appears a moment later.
    openTab('General')
    await waitFor(() => expect(partsOnScreen()).toEqual(['brief', 'desktop', 'parts']))
  })

  it('leaves a tab that has not been opened out of the document, and a part with nothing to keep when its tab is left', async () => {
    render(<SettingsPage />)
    await screen.findByLabelText('Brief time')
    for (const name of ['engines', 'appearance', 'extension', 'bring-in', 'vault', 'filing', 'privacy', 'usage']) expect(partNamed(name)).toBeNull()
    openTab('Privacy and usage')
    expect(partNamed('privacy')).not.toBeNull()
    openTab('General')
    expect(partNamed('privacy')).toBeNull()
    expect(partNamed('usage')).toBeNull()
    expect(partNamed('desktop')).not.toBeNull()
    openTab('Appearance')
    expect(partNamed('desktop')).toBeNull()
  })

  it('opens the tab that holds the part named in the address, and scrolls the part into view', async () => {
    const scroll = vi.fn()
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = scroll
    window.location.hash = '#/settings?section=bring-in'
    try {
      render(<SettingsPage />)
      expect(screen.getByRole('tab', { name: 'Bringing things in' })).toHaveAttribute('aria-selected', 'true')
      expect(partsOnScreen()).toEqual(['extension', 'bring-in'])
      await waitFor(() => expect(scroll).toHaveBeenCalled())
    } finally {
      Element.prototype.scrollIntoView = original
    }
  })

  it.each([
    ['engines', 'AI engines'],
    ['extension', 'Bringing things in'],
    ['vault', 'Vault and filing'],
    ['usage', 'Privacy and usage'],
    ['appearance', 'Appearance'],
    ['desktop', 'General'],
  ])('opens %s on the tab "%s"', (section, tab) => {
    window.location.hash = `#/settings?section=${section}`
    render(<SettingsPage />)
    expect(screen.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true')
  })

  it('moves to the tab of a part named by a link followed while the page is open', async () => {
    render(<SettingsPage />)
    expect(screen.getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
    act(() => {
      window.location.hash = '#/settings?section=vault'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Vault and filing' })).toHaveAttribute('aria-selected', 'true'))
    expect(partsOnScreen()).toEqual(['vault', 'filing'])
  })

  it('opens General when the address names no part, or one that does not exist', () => {
    window.location.hash = '#/settings?section=nothing'
    render(<SettingsPage />)
    expect(screen.getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
  })

  it('keeps what was typed and not yet saved in the Daily brief, the Vault, and an engine key, when the reader comes back', async () => {
    render(<SettingsPage />)
    fireEvent.change(await screen.findByLabelText('Brief time'), { target: { value: '07:45' } })
    openTab('AI engines')
    await showEveryEngine()
    fireEvent.change(await screen.findByLabelText('API key for OpenAI'), { target: { value: SECRET } })
    openTab('Vault and filing')
    fireEvent.change(await screen.findByLabelText('Vault folder'), { target: { value: 'D:/Unsaved' } })
    // On another tab the parts are hidden: they are not on screen, yet the typed text is still held.
    openTab('Privacy and usage')
    expect(partsOnScreen()).toEqual(['privacy', 'usage'])
    expect(screen.getByLabelText('Vault folder')).not.toBeVisible()
    openTab('General')
    expect(screen.getByLabelText('Brief time')).toHaveValue('07:45')
    openTab('AI engines')
    expect(screen.getByLabelText('API key for OpenAI')).toHaveValue(SECRET)
    expect(screen.getByRole('button', { name: 'Show only the engines that are set up' })).toBeInTheDocument()
    openTab('Vault and filing')
    expect(screen.getByLabelText('Vault folder')).toHaveValue('D:/Unsaved')
    expect(api.patchSettings).not.toHaveBeenCalled()
  })

  it('shows the loading error of the settings on every tab that needs them, and only there', async () => {
    api.loadSettings.mockRejectedValueOnce(new ApiError('Spyglass is not reachable. Check that the service is running, then try again.', { status: 0, kind: 'network', path: '/api/settings' }))
    render(<SettingsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Spyglass is not reachable')
    // AI engines needs them for the default engine and the choice of which AI judges.
    openTab('AI engines')
    await screen.findByText('OpenRouter', { selector: '.rst-name' })
    expect(screen.getByRole('alert')).toHaveTextContent('Spyglass is not reachable')
    openTab('Appearance')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

/** The engine rows the reader can see (rows folded away stay in the document, hidden). */
const visibleEngines = () => Array.from(document.querySelectorAll('.rst-engine')).filter((row) => !row.closest('[hidden]'))

describe('The list of AI engines', () => {
  /** Nine engines, the first two set up. */
  function nine(): EngineRow[] {
    return [
      engine({ id: 'e1', label: 'Engine One' }),
      engine({ id: 'e2', label: 'Engine Two' }),
      ...[3, 4, 5, 6, 7, 8, 9].map((n) => engine({ id: `e${n}`, label: `Engine ${n}`, available: false, reason: 'Not set up.', models: [] })),
    ]
  }

  it('lists only the engines that are set up, then every engine after one button, and back', async () => {
    api.loadEngines.mockResolvedValue(nine())
    render(<SettingsPage />)
    openTab('AI engines')
    expect(await screen.findByText('Engine One', { selector: '.rst-name' })).toBeInTheDocument()
    expect(visibleEngines()).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Show the 7 engines that are not set up' }))
    expect(visibleEngines()).toHaveLength(9)
    fireEvent.click(screen.getByRole('button', { name: 'Show only the engines that are set up' }))
    expect(visibleEngines()).toHaveLength(2)
  })

  it('keeps a key typed into an engine that is not set up when the list is folded and unfolded', async () => {
    api.loadEngines.mockResolvedValue([engine({ id: 'e1', label: 'Engine One' }), engine({ id: 'e2', label: 'Engine Two', available: false, needs_key: true, models: [] })])
    render(<SettingsPage />)
    openTab('AI engines')
    await showEveryEngine()
    fireEvent.change(await screen.findByLabelText('API key for Engine Two'), { target: { value: SECRET } })
    fireEvent.click(screen.getByRole('button', { name: 'Show only the engines that are set up' }))
    // Folded: the row is out of sight, not in the list the reader sees.
    expect(visibleEngines()).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Show the 1 engine that is not set up' }))
    expect(screen.getByLabelText('API key for Engine Two')).toHaveValue(SECRET)
  })

  it('says "engine that is" for one engine that is not set up', async () => {
    api.loadEngines.mockResolvedValue([engine({ id: 'e1', label: 'Engine One' }), engine({ id: 'e2', label: 'Engine Two', available: false, models: [] })])
    render(<SettingsPage />)
    openTab('AI engines')
    expect(await screen.findByRole('button', { name: 'Show the 1 engine that is not set up' })).toBeInTheDocument()
  })

  it('shows the whole list and no button when none is set up, or when all are', async () => {
    api.loadEngines.mockResolvedValue(nine().map((entry) => ({ ...entry, available: false })))
    const none = render(<SettingsPage />)
    openTab('AI engines')
    expect(await screen.findByText('Engine One', { selector: '.rst-name' })).toBeInTheDocument()
    expect(visibleEngines()).toHaveLength(9)
    expect(screen.queryByRole('button', { name: /not set up|set up$/ })).not.toBeInTheDocument()
    none.unmount()

    api.loadEngines.mockResolvedValue(nine().map((entry) => ({ ...entry, available: true })))
    render(<SettingsPage />)
    openTab('AI engines')
    expect(await screen.findByText('Engine One', { selector: '.rst-name' })).toBeInTheDocument()
    expect(visibleEngines()).toHaveLength(9)
    expect(screen.queryByRole('button', { name: /not set up|set up$/ })).not.toBeInTheDocument()
  })

  it('keeps an engine the reader switches off in view, with its note and the focus, until the list is folded', async () => {
    api.loadEngines.mockResolvedValue([
      engine({ id: 'e1', label: 'Engine One' }),
      engine({ id: 'claude_code', label: 'Claude Code', kind: 'cli', available: true, enabled: true, models: [] }),
      engine({ id: 'e3', label: 'Engine 3', available: false, models: [] }),
    ])
    // Switched off, the command-line engine is no longer available, which would fold it away.
    api.configureEngine.mockImplementation(async (id: string, change: { enabled?: boolean }) => ({
      ...engine({ id, label: 'Claude Code', kind: 'cli', models: [] }),
      enabled: change.enabled,
      available: change.enabled === true,
    }))
    render(<SettingsPage />)
    openTab('AI engines')
    const toggle = await screen.findByRole('switch', { name: 'Use Claude Code' })
    toggle.focus()
    fireEvent.click(toggle)
    expect(await screen.findByText('Switched off.')).toBeVisible()
    expect(toggle).toBeVisible()
    expect(document.activeElement).toBe(toggle)
    expect(visibleEngines()).toHaveLength(2)
    // The button counts only the engines it hides.
    fireEvent.click(screen.getByRole('button', { name: 'Show the 1 engine that is not set up' }))
    fireEvent.click(screen.getByRole('button', { name: 'Show only the engines that are set up' }))
    expect(toggle).not.toBeVisible()
    expect(visibleEngines()).toHaveLength(1)
  })

  it('still offers to fold the list after the reader unfolds it and changes every engine that is not set up', async () => {
    api.loadEngines.mockResolvedValue([
      engine({ id: 'e1', label: 'Engine One' }),
      engine({ id: 'claude_code', label: 'Claude Code', kind: 'cli', available: false, reason: 'Switched off', enabled: false, models: [] }),
    ])
    // Switched on, the program is still not found on this computer, so the engine stays not set up.
    api.configureEngine.mockImplementation(async (id: string, change: { enabled?: boolean }) => ({
      ...engine({ id, label: 'Claude Code', kind: 'cli', models: [] }),
      enabled: change.enabled,
      available: false,
      reason: 'The program was not found.',
    }))
    render(<SettingsPage />)
    openTab('AI engines')
    fireEvent.click(await screen.findByRole('button', { name: 'Show the 1 engine that is not set up' }))
    fireEvent.click(await screen.findByRole('switch', { name: 'Use Claude Code' }))
    expect(await screen.findByText('Switched on.')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Show only the engines that are set up' }))
    expect(visibleEngines()).toHaveLength(1)
  })

  it('counts a custom server the reader added as set up, so it does not vanish when its server is down', async () => {
    api.loadEngines.mockResolvedValue([
      engine({ id: 'e1', label: 'Engine One' }),
      engine({ id: 'custom-x', label: 'Lab box', kind: 'custom', custom: true, available: false, models: [], base_url: 'http://10.0.0.5/v1' }),
      engine({ id: 'e3', label: 'Engine 3', available: false, models: [] }),
    ])
    render(<SettingsPage />)
    openTab('AI engines')
    expect(await screen.findByText('Lab box', { selector: '.rst-name' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show the 1 engine that is not set up' })).toBeInTheDocument()
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
