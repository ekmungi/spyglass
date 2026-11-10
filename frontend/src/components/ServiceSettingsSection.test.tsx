// The background-job settings in the Settings tab.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ServiceSettingsSection } from './ServiceSettingsSection'

const SETTINGS = {
  vault_path: '/vault', feed_note_path: null, interest_note_path: null, preferences_note_path: null,
  port: 7777, fulltext_refresh_hours: 24, relevance_threshold: 'medium', relevance_model: 'haiku',
  yt_transcribe_cmd: '', inbox_channel: 'paper-inbox',
  claude_command: null, job_timeout_minutes: 10, detail_notes_subdir: '03 RESOURCES/Spyglass/Brief notes',
  obsidian_mcp_server: 'obsidian-vault', obsidian_probe_url: 'http://127.0.0.1:27123/',
}

afterEach(() => vi.unstubAllGlobals())

describe('ServiceSettingsSection', () => {
  it('edits and saves the background-job settings', async () => {
    const patches: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PATCH') patches.push(JSON.parse(String(init.body)))
      return new Response(JSON.stringify(SETTINGS))
    }))
    render(<ServiceSettingsSection />)
    const limit = await screen.findByLabelText(/job time limit/i)
    expect(screen.getByLabelText(/detail notes folder/i)).toHaveValue('03 RESOURCES/Spyglass/Brief notes')
    expect(screen.getByLabelText(/obsidian mcp server/i)).toHaveValue('obsidian-vault')
    fireEvent.change(screen.getByLabelText(/obsidian address/i), { target: { value: 'https://127.0.0.1:27124/' } })
    fireEvent.change(limit, { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText(/claude command/i), { target: { value: 'C:/claude.exe' } })
    fireEvent.click(screen.getByRole('button', { name: /save settings/i }))
    await waitFor(() => expect(patches).toHaveLength(1))
    expect(patches[0]).toMatchObject({ job_timeout_minutes: 5, claude_command: 'C:/claude.exe', obsidian_probe_url: 'https://127.0.0.1:27124/' })
  })

  it('hides them for a service without background jobs', async () => {
    const older = { ...SETTINGS, claude_command: undefined, job_timeout_minutes: undefined, detail_notes_subdir: undefined }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(older))))
    render(<ServiceSettingsSection />)
    await screen.findByText(/inbox slack channel/i)
    expect(screen.queryByLabelText(/job time limit/i)).not.toBeInTheDocument()
  })
})
