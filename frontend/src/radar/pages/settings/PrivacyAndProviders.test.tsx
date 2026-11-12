// Tests for the Privacy section (sentences, four switches, two disclosures), the "AI for the daily
// judging" block (first choice, fallback order, saving), and a command-line engine of any id.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import type { PrivacyOutbound } from '../../api/types'
import { EngineItem } from './EngineItem'
import { JudgingProviders } from './JudgingProviders'
import { PrivacySection } from './PrivacySection'
import { PRIVACY_SWITCHES } from './privacySwitches'
import { joinFallback, MAX_FALLBACK, parseFallback, PROVIDERS } from './providers'
import type { EngineRow } from './api'

const api = vi.hoisted(() => ({ loadPrivacy: vi.fn(), patchSettings: vi.fn(), configureEngine: vi.fn(), removeEngine: vi.fn() }))
vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./api')>()), ...api }))

const overview = (over: Partial<PrivacyOutbound> = {}): PrivacyOutbound => ({
  model_provider: { name: 'OpenRouter', host: 'openrouter.ai' },
  profile_block: 'Someone who follows AI closely and builds with AI agents, and wants a short daily picture of AI and the fields they care about.',
  example_titles: { liked: ['Endovista wins clearance'], disliked: ['Ten puzzle games'] },
  destinations: [
    { name: 'OpenRouter', host: 'openrouter.ai', purpose: 'Judges items', what_is_sent: 'Your profile and the item text', carries_secret: true, enabled: true },
    { name: 'arXiv', host: 'export.arxiv.org', purpose: 'Finds papers', what_is_sent: 'Your topic words', carries_secret: false, enabled: true },
    { name: 'Jina Reader', host: 'r.jina.ai', purpose: 'Reads blocked pages', what_is_sent: 'The page address', carries_secret: true, enabled: false },
  ],
  switches: { privacy_send_examples: true, privacy_proxy_images: true, jina_enabled: false, privacy_allow_bot_checks: true },
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.loadPrivacy.mockResolvedValue(overview())
  api.patchSettings.mockImplementation(async (change: Record<string, unknown>) => change)
})

describe('PrivacySection', () => {
  it('opens with the three plain sentences and ends with where the full note is', async () => {
    render(<PrivacySection />)
    expect(await screen.findByText(/Spyglass never signs in anywhere, never sends cookies and never posts anything\. Only program code fetches pages, and it only reads\. The AI has no tools: it cannot browse, open files or run commands\./)).toBeInTheDocument()
    expect(screen.getByText("The full note is in the application's docs folder: privacy-and-safety.md.")).toBeInTheDocument()
  })

  it('shows four switches with the reader\'s own words, in the state the service reports', async () => {
    render(<PrivacySection />)
    await screen.findByRole('switch', { name: PRIVACY_SWITCHES[0].label })
    expect(PRIVACY_SWITCHES.map((entry) => entry.label)).toEqual([
      'Send titles of items I saved as examples of my taste',
      'Load article images through Spyglass, so the sites never see my browser',
      "Let the built-in browser complete a site's automated check (sends technical details of that browser, never anything personal)",
      'Use an outside rendering service for pages that block Spyglass (it learns which pages I read)',
    ])
    expect(screen.getAllByRole('switch')).toHaveLength(4)
    expect(screen.getByRole('switch', { name: /Send titles/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('switch', { name: /Load article images/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('switch', { name: /built-in browser/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('switch', { name: /outside rendering service/ })).toHaveAttribute('aria-checked', 'false')
  })

  it('saves a switch through the settings under its own name', async () => {
    render(<PrivacySection />)
    fireEvent.click(await screen.findByRole('switch', { name: /outside rendering service/ }))
    await waitFor(() => expect(api.patchSettings).toHaveBeenCalledWith({ jina_enabled: true }))
    await waitFor(() => expect(screen.getByRole('switch', { name: /outside rendering service/ })).toHaveAttribute('aria-checked', 'true'))
    fireEvent.click(screen.getByRole('switch', { name: /Send titles/ }))
    await waitFor(() => expect(api.patchSettings).toHaveBeenCalledWith({ privacy_send_examples: false }))
    await waitFor(() => expect(screen.getByRole('switch', { name: /Send titles/ })).toHaveAttribute('aria-checked', 'false'))
  })

  it('leaves a switch as it was and says why when saving fails', async () => {
    api.patchSettings.mockRejectedValue(new ApiError('Settings are read-only.', { status: 422, kind: 'http', path: '/api/settings', detail: 'x' }))
    render(<PrivacySection />)
    fireEvent.click(await screen.findByRole('switch', { name: /outside rendering service/ }))
    expect(await screen.findByText('Settings are read-only.')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: /outside rendering service/ })).toHaveAttribute('aria-checked', 'false')
  })

  it('does not claim success when the service does not confirm the new value', async () => {
    api.patchSettings.mockResolvedValue({})
    render(<PrivacySection />)
    fireEvent.click(await screen.findByRole('switch', { name: /outside rendering service/ }))
    expect(await screen.findByText(/did not confirm this choice/)).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: /outside rendering service/ })).toHaveAttribute('aria-checked', 'false')
  })

  it('shows exactly what the AI is sent, read-only, with the example titles in two lists', async () => {
    render(<PrivacySection />)
    fireEvent.click(await screen.findByText('What is sent to the AI right now'))
    const box = screen.getByLabelText('The profile text sent to the AI')
    expect(box).toHaveValue('Someone who follows AI closely and builds with AI agents, and wants a short daily picture of AI and the fields they care about.')
    expect(box).toHaveAttribute('readonly')
    expect(screen.getByText(/OpenRouter \(openrouter\.ai\)/)).toBeInTheDocument()
    expect(screen.getByText('Endovista wins clearance')).toBeInTheDocument()
    expect(screen.getByText('Ten puzzle games')).toBeInTheDocument()
  })

  it('says titles are not sent when that switch is off', async () => {
    render(<PrivacySection />)
    fireEvent.click(await screen.findByRole('switch', { name: /Send titles/ }))
    await waitFor(() => expect(screen.getByRole('switch', { name: /Send titles/ })).toHaveAttribute('aria-checked', 'false'))
    expect(screen.getByText('Titles of items you saved are not sent, because that switch is off.')).toBeInTheDocument()
    expect(screen.queryByText('Endovista wins clearance')).not.toBeInTheDocument()
  })

  it('lists where Spyglass connects, marks a key, and dims what is switched off', async () => {
    render(<PrivacySection />)
    fireEvent.click(await screen.findByText('Where Spyglass connects'))
    const openrouter = screen.getByText('OpenRouter', { selector: '.rst-name' }).closest('li') as HTMLElement
    expect(within(openrouter).getByText('carries a key')).toBeInTheDocument()
    expect(within(openrouter).getByText('Judges items')).toBeInTheDocument()
    expect(within(openrouter).getByText('Sent: Your profile and the item text')).toBeInTheDocument()
    expect(openrouter).toHaveAttribute('data-enabled', 'true')
    const arxiv = screen.getByText('arXiv', { selector: '.rst-name' }).closest('li') as HTMLElement
    expect(within(arxiv).queryByText('carries a key')).not.toBeInTheDocument()
    const jina = screen.getByText('Jina Reader', { selector: '.rst-name' }).closest('li') as HTMLElement
    expect(jina).toHaveAttribute('data-enabled', 'false')
    expect(within(jina).getByText('switched off')).toBeInTheDocument()
  })

  it('says calmly that the overview is not available yet when the service has none', async () => {
    api.loadPrivacy.mockResolvedValue(null)
    render(<PrivacySection />)
    expect(await screen.findByText('The privacy overview is not available in this copy of Spyglass yet.')).toBeInTheDocument()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
    expect(screen.getByText(/Spyglass never signs in anywhere/)).toBeInTheDocument()
  })

  it('offers Try again when loading fails', async () => {
    api.loadPrivacy.mockRejectedValueOnce(new ApiError('Spyglass is not reachable.', { status: 0, kind: 'network', path: '/privacy/outbound' }))
    render(<PrivacySection />)
    expect(await screen.findByText('Spyglass is not reachable.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findAllByRole('switch')).toHaveLength(4)
  })
})

describe('provider order helpers', () => {
  it('reads the stored fallback: known names only, no repeats, at most three', () => {
    expect(parseFallback('gemini, antigravity')).toEqual(['gemini', 'antigravity'])
    expect(parseFallback('gemini,gemini,nonsense,openrouter,claude_code,antigravity')).toEqual(['gemini', 'openrouter', 'claude_code'])
    expect(parseFallback('')).toEqual([])
    expect(parseFallback(undefined)).toEqual([])
    expect(MAX_FALLBACK).toBe(3)
    expect(joinFallback(['gemini', 'antigravity'])).toBe('gemini,antigravity')
    expect(joinFallback([])).toBe('')
    expect(PROVIDERS.map((provider) => provider.id)).toEqual(['openrouter', 'claude_code', 'gemini', 'antigravity'])
  })
})

function engine(over: Partial<EngineRow> & { id: string; label: string }): EngineRow {
  return { kind: 'api', available: true, reason: null, models: [], default_model: null, enabled: true, needs_key: false, has_key: false, key_source: null, base_url: null, custom: false, ...over }
}

const ENGINES = [
  engine({ id: 'openrouter', label: 'OpenRouter', needs_key: true, has_key: true }),
  engine({ id: 'claude', label: 'Claude (subscription)', kind: 'cli' }),
  engine({ id: 'gemini', label: 'Google Gemini API', available: false, reason: 'No API key saved.', needs_key: true }),
  engine({ id: 'antigravity', label: 'Antigravity (your Google plan)', kind: 'cli', available: false, reason: 'Not signed in on this computer.', enabled: false }),
]

function renderJudging(settings: Record<string, unknown> = { radar_llm_provider: 'openrouter', radar_llm_fallback: '' }) {
  const onSaved = vi.fn()
  render(<JudgingProviders engines={ENGINES} settings={settings} onSaved={onSaved} />)
  return onSaved
}

describe('JudgingProviders', () => {
  it('explains the fallback in one sentence and shows the saved first choice and order', () => {
    renderJudging({ radar_llm_provider: 'claude_code', radar_llm_fallback: 'gemini,antigravity' })
    expect(screen.getByRole('heading', { name: 'AI for the daily judging' })).toBeInTheDocument()
    expect(screen.getByText('If the first is out of credit, at its limit or not signed in, the next is used.')).toBeInTheDocument()
    expect((screen.getByLabelText('First choice') as HTMLSelectElement).value).toBe('claude_code')
    const list = screen.getByRole('list', { name: 'Then try, in order' })
    expect(within(list).getAllByRole('listitem').map((item) => item.firstElementChild?.textContent)).toEqual(['1. Google Gemini API', '2. Antigravity (your Google plan)'])
  })

  it('lists AIs that are not available with a note, and still lets them be chosen', () => {
    renderJudging()
    const options = Array.from((screen.getByLabelText('First choice') as HTMLSelectElement).options).map((option) => option.text)
    expect(options).toEqual(['OpenRouter', 'Claude (subscription)', 'Google Gemini API (not available now)', 'Antigravity (your Google plan) (not available now)'])
    fireEvent.change(screen.getByLabelText('First choice'), { target: { value: 'antigravity' } })
    expect((screen.getByLabelText('First choice') as HTMLSelectElement).value).toBe('antigravity')
    expect(screen.getByText('Antigravity (your Google plan): Not signed in on this computer.')).toBeInTheDocument()
  })

  it('builds the fallback order with add and remove, at most three, and saves both settings', async () => {
    const onSaved = renderJudging()
    expect(screen.getByRole('button', { name: 'Save choices' })).toBeDisabled()
    const add = () => screen.getByLabelText('Add another AI')
    fireEvent.change(add(), { target: { value: 'gemini' } })
    fireEvent.change(add(), { target: { value: 'claude_code' } })
    fireEvent.change(add(), { target: { value: 'antigravity' } })
    // Three is the limit, so there is nothing more to add.
    expect(screen.queryByLabelText('Add another AI')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove Google Gemini API from the list' }))
    expect(within(screen.getByRole('list', { name: 'Then try, in order' })).getAllByRole('listitem').map((item) => item.firstElementChild?.textContent)).toEqual(['1. Claude (subscription)', '2. Antigravity (your Google plan)'])
    fireEvent.click(screen.getByRole('button', { name: 'Save choices' }))
    await waitFor(() => expect(api.patchSettings).toHaveBeenCalledWith({ radar_llm_provider: 'openrouter', radar_llm_fallback: 'claude_code,antigravity' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ radar_llm_provider: 'openrouter', radar_llm_fallback: 'claude_code,antigravity' }))
  })

  it('takes the new first choice out of the fallback list', () => {
    renderJudging({ radar_llm_provider: 'openrouter', radar_llm_fallback: 'gemini,claude_code' })
    fireEvent.change(screen.getByLabelText('First choice'), { target: { value: 'gemini' } })
    expect(within(screen.getByRole('list', { name: 'Then try, in order' })).getAllByRole('listitem').map((item) => item.firstElementChild?.textContent)).toEqual(['1. Claude (subscription)'])
  })

  it('shows the failure and keeps the choices when saving fails', async () => {
    api.patchSettings.mockRejectedValue(new ApiError('Settings are read-only.', { status: 422, kind: 'http', path: '/api/settings', detail: 'x' }))
    const onSaved = renderJudging()
    fireEvent.change(screen.getByLabelText('First choice'), { target: { value: 'gemini' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save choices' }))
    expect(await screen.findByText('Settings are read-only.')).toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
    expect((screen.getByLabelText('First choice') as HTMLSelectElement).value).toBe('gemini')
  })
})

describe('a command-line engine, whatever its id', () => {
  it.each(['antigravity', 'some-future-cli'])('shows an enable switch, the generic sentence and no key field for "%s"', (id) => {
    api.configureEngine.mockImplementation(async (_id: string, change: Record<string, unknown>) => ({ ...ENGINES[3], id, ...change }))
    const onChange = vi.fn()
    render(<EngineItem engine={engine({ id, label: 'Some CLI', kind: 'cli', enabled: false, available: false, reason: 'Not signed in.' })} onChange={onChange} onRemoved={vi.fn()} />)
    expect(screen.getByRole('switch', { name: 'Use Some CLI' })).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByText('Uses the program and sign-in already on this computer, for your personal use only.')).toBeInTheDocument()
    expect(screen.getByText('Not signed in.')).toBeInTheDocument()
    expect(screen.queryByLabelText(/API key/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('switch', { name: 'Use Some CLI' }))
    expect(api.configureEngine).toHaveBeenCalledWith(id, { enabled: true })
  })

  it('shows the same for an engine of another kind that has a switch but needs no key', () => {
    render(<EngineItem engine={engine({ id: 'odd', label: 'Odd engine', kind: 'plugin', enabled: true })} onChange={vi.fn()} onRemoved={vi.fn()} />)
    expect(screen.getByRole('switch', { name: 'Use Odd engine' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByLabelText(/API key/)).not.toBeInTheDocument()
  })

  it('still asks for a key for a hosted engine', () => {
    render(<EngineItem engine={engine({ id: 'gemini', label: 'Google Gemini API', kind: 'api', needs_key: true, available: false })} onChange={vi.fn()} onRemoved={vi.fn()} />)
    expect(screen.getByLabelText('API key for Google Gemini API')).toBeInTheDocument()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
  })
})
