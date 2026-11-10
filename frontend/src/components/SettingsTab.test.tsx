// Tests for the settings tab: theme/sizes stay editable + service settings.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_SIZES } from '../lib/presets'
import { SettingsTab } from './SettingsTab'

const SERVICE_SETTINGS = {
  vault_path: 'C:/vault',
  feed_note_path: '00 INBOX/Spyglass/feed.md',
  interest_note_path: '00 INBOX/Spyglass/interests.md',
  preferences_note_path: '00 INBOX/Spyglass/preferences.md',
  port: 7777,
  fulltext_refresh_hours: 24,
  relevance_threshold: 'medium',
  relevance_model: 'haiku',
}

function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    // The category manager section fetches /api/categories on mount.
    if (String(input).includes('/api/categories')) {
      return new Response(JSON.stringify([]), { status: 200 })
    }
    if (init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      return new Response(JSON.stringify({ ...SERVICE_SETTINGS, ...body }), { status: 200 })
    }
    return new Response(JSON.stringify(SERVICE_SETTINGS), { status: 200 })
  })
}

describe('SettingsTab', () => {
  beforeEach(() => vi.stubGlobal('fetch', stubFetch()))
  afterEach(() => vi.unstubAllGlobals())

  it('renders as a centered fixed-width card unaffected by the workspace width', () => {
    const { container } = render(<SettingsTab />)
    const card = container.firstChild as HTMLElement
    expect(card.className).toContain('mx-auto')
    expect(card.className).toContain('max-w-[680px]')
    expect(card.className).toContain('bg-card')
  })

  it('keeps the full 48-preset theme picker and applies a selection', () => {
    render(<SettingsTab />)
    const select = screen.getByLabelText(/theme/i) as HTMLSelectElement
    expect(select.options).toHaveLength(48)
    fireEvent.change(select, { target: { value: 'warm-dark-classic' } })
    expect(document.documentElement.dataset.theme).toBe('warm-dark-classic')
  })

  it('keeps the editable font-size sliders', () => {
    render(<SettingsTab />)
    fireEvent.change(screen.getByLabelText(/summary text/i), { target: { value: '17' } })
    expect(document.documentElement.style.getPropertyValue('--font-size-body')).toBe('17px')
  })

  it('adjusts the workspace width and the pane split, and persists them', () => {
    render(<SettingsTab />)
    fireEvent.change(screen.getByLabelText(/workspace width/i), { target: { value: '1600' } })
    fireEvent.change(screen.getByLabelText(/list pane width/i), { target: { value: '45' } })
    const root = document.documentElement
    expect(root.style.getPropertyValue('--layout-max-width')).toBe('1600px')
    expect(root.style.getPropertyValue('--list-pane-width')).toBe('45%')
    const stored = JSON.parse(localStorage.getItem('spyglass-appearance')!)
    expect(stored.layout).toEqual({ maxWidth: 1600, listWidth: 45 })
  })

  it('reset restores the locked default sizes', () => {
    render(<SettingsTab />)
    fireEvent.change(screen.getByLabelText(/summary text/i), { target: { value: '18' } })
    fireEvent.click(screen.getByRole('button', { name: /reset/i }))
    expect(document.documentElement.style.getPropertyValue('--font-size-body')).toBe(
      `${DEFAULT_SIZES.body}px`,
    )
  })

  it('loads the service settings into editable fields', async () => {
    render(<SettingsTab />)
    expect(await screen.findByDisplayValue('00 INBOX/Spyglass/interests.md')).toBeInTheDocument()
    expect(screen.getByDisplayValue('C:/vault')).toBeInTheDocument()
    expect(screen.getByDisplayValue('7777')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /browse/i })).toBeInTheDocument()
  })

  it('saves edited research settings through PATCH /api/settings', async () => {
    const stub = stubFetch()
    vi.stubGlobal('fetch', stub)
    render(<SettingsTab />)
    await screen.findByDisplayValue('24')
    fireEvent.change(screen.getByLabelText('Full-text refresh cadence (hours)'), {
      target: { value: '6' },
    })
    fireEvent.change(screen.getByLabelText('Relevance / learning model'), {
      target: { value: 'sonnet' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() => {
      const patch = stub.mock.calls.find((c) => c[1]?.method === 'PATCH')
      expect(patch).toBeDefined()
      expect(JSON.parse(String(patch![1]!.body))).toMatchObject({
        fulltext_refresh_hours: 6,
        relevance_model: 'sonnet',
      })
    })
    expect(await screen.findByText(/saved/i)).toBeInTheDocument()
  })

  it('offers the relevance threshold default selector', async () => {
    render(<SettingsTab />)
    const select = (await screen.findByLabelText(
      'Relevance threshold (default)',
    )) as HTMLSelectElement
    expect([...select.options].map((o) => o.value)).toEqual(['high', 'medium', 'low', 'out'])
  })

  it('shows feed note field as import-only with a helper description', async () => {
    render(<SettingsTab />)
    // The label text must indicate import-only status (not "live source").
    expect(await screen.findByText('Feed note (import only)')).toBeInTheDocument()
    // The helper description explains where feeds are managed now.
    expect(
      screen.getByText(/Feeds are now managed in the Feeds tab/i),
    ).toBeInTheDocument()
    // The field itself still renders and holds the path from the fixture.
    expect(screen.getByDisplayValue('00 INBOX/Spyglass/feed.md')).toBeInTheDocument()
  })
})
