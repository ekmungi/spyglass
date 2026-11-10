// Service settings sections: vault paths, port, and research settings,
// loaded from and persisted to the service's settings overlay.
import { useEffect, useState } from 'react'
import * as api from '../lib/api'
import type { ServiceSettings } from '../lib/types'

/** One labelled settings row with a text-style input.
 *
 * @param label    - The visible label text (also used as the accessible label).
 * @param value    - Controlled input value.
 * @param width    - Optional CSS width for the input (default 260px).
 * @param onChange - Called with the new string value on every change.
 * @param description - Optional helper text shown below the label in muted style.
 */
function Field({
  label,
  value,
  width,
  onChange,
  description,
}: {
  label: string
  value: string
  width?: string
  onChange: (value: string) => void
  description?: string
}) {
  return (
    <label className="flex items-center justify-between gap-3 border-b border-border py-1.5 text-body last:border-b-0">
      <span className="flex flex-col gap-0.5">
        <span>{label}</span>
        {description && (
          <span className="text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
            {description}
          </span>
        )}
      </span>
      <input
        type="text"
        className="border border-border bg-canvas px-2 py-1 text-body"
        style={{ borderRadius: 'var(--radius-control)', width: width ?? '260px' }}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

/** Vault + Research sections with a single save action and restart hint. */
export function ServiceSettingsSection() {
  const [settings, setSettings] = useState<ServiceSettings | null>(null)
  const [status, setStatus] = useState('')

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => setStatus('settings unavailable'))
  }, [])

  if (settings === null) {
    return <p className="mt-6 text-muted">{status || 'Loading service settings...'}</p>
  }

  const set = (patch: Partial<ServiceSettings>) => {
    setSettings({ ...settings, ...patch })
    setStatus('')
  }

  const save = () => {
    api
      .patchSettings(settings)
      .then((saved) => {
        setSettings(saved)
        setStatus('Saved. Port changes apply after a service restart.')
      })
      .catch(() => setStatus('Save failed'))
  }

  const browse = async () => {
    // The File System Access API exposes only the folder NAME, not its path, so
    // Browse is an assist for supported browsers; the path stays editable text.
    const picker = (
      window as Window & { showDirectoryPicker?: () => Promise<{ name: string }> }
    ).showDirectoryPicker
    if (!picker) {
      setStatus('Folder picking is not available here; edit the path directly.')
      return
    }
    try {
      const dir = await picker()
      setStatus(`Picked "${dir.name}" -- confirm the full path in the field.`)
    } catch {
      // User cancelled the picker; nothing to do.
    }
  }

  return (
    <div className="mt-6" style={{ fontSize: 'var(--font-size-actions)' }}>
      <h3 className="mb-1 font-semibold text-ink" style={{ fontSize: 'var(--font-size-body)' }}>
        Vault
      </h3>
      <label className="flex items-center justify-between gap-3 border-b border-border py-1.5 text-body">
        Vault root
        <span className="flex gap-1.5">
          <input
            type="text"
            className="border border-border bg-canvas px-2 py-1 text-body"
            style={{ borderRadius: 'var(--radius-control)', width: '220px' }}
            value={settings.vault_path ?? ''}
            onChange={(event) => set({ vault_path: event.target.value })}
          />
          <button
            type="button"
            className="border border-border px-2.5 py-1 text-body hover:border-accent"
            style={{ borderRadius: 'var(--radius-control)' }}
            onClick={browse}
          >
            Browse...
          </button>
        </span>
      </label>
      <Field
        label="Feed note (import only)"
        description="Feeds are now managed in the Feeds tab; this path is only used for one-off import."
        value={settings.feed_note_path ?? ''}
        onChange={(value) => set({ feed_note_path: value })}
      />
      <Field
        label="Interests note"
        value={settings.interest_note_path ?? ''}
        onChange={(value) => set({ interest_note_path: value })}
      />
      <Field
        label="Preferences note (learned)"
        value={settings.preferences_note_path ?? ''}
        onChange={(value) => set({ preferences_note_path: value })}
      />
      <Field
        label="Service port"
        value={String(settings.port)}
        width="80px"
        onChange={(value) => set({ port: Number(value) || settings.port })}
      />

      <h3 className="mb-1 mt-5 font-semibold text-ink" style={{ fontSize: 'var(--font-size-body)' }}>
        Research
      </h3>
      <Field
        label="Full-text refresh cadence (hours)"
        value={String(settings.fulltext_refresh_hours)}
        width="80px"
        onChange={(value) => set({ fulltext_refresh_hours: Number(value) || 0 })}
      />
      <label className="flex items-center justify-between gap-3 border-b border-border py-1.5 text-body">
        Relevance threshold (default)
        <select
          className="border border-border bg-card px-2 py-1 text-body"
          style={{ borderRadius: 'var(--radius-control)' }}
          value={settings.relevance_threshold}
          onChange={(event) =>
            set({ relevance_threshold: event.target.value as ServiceSettings['relevance_threshold'] })
          }
        >
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
          <option value="out">Show all</option>
        </select>
      </label>
      <label className="flex items-center justify-between gap-3 py-1.5 text-body">
        Relevance / learning model
        <select
          className="border border-border bg-card px-2 py-1 text-body"
          style={{ borderRadius: 'var(--radius-control)' }}
          value={settings.relevance_model}
          onChange={(event) =>
            set({ relevance_model: event.target.value as ServiceSettings['relevance_model'] })
          }
        >
          <option value="haiku">Haiku</option>
          <option value="sonnet">Sonnet</option>
        </select>
      </label>

      <h3 className="mb-1 mt-5 font-semibold text-ink" style={{ fontSize: 'var(--font-size-body)' }}>
        Integrations
      </h3>
      <Field
        label="Inbox Slack channel"
        description="The channel you drop papers into for the paper inbox, e.g. paper-inbox. Claude reads it through your Slack connector in the Claude desktop app and never posts there."
        value={settings.inbox_channel ?? ''}
        onChange={(value) => set({ inbox_channel: value })}
      />
      <Field
        label="yt-transcribe CLI path (video transcripts)"
        description="Path to the yt-transcribe tool. Leave blank to auto-detect (PATH, ~/.local/bin, or your YouTube Transcribe plugin's setting). Videos fall back to the built-in caption fetch if it's missing."
        value={settings.yt_transcribe_cmd ?? ''}
        onChange={(value) => set({ yt_transcribe_cmd: value })}
      />
      {settings.job_timeout_minutes !== undefined && (
        <>
          <Field
            label="Claude command (background jobs)"
            description="Claude Code, which runs Prepare detail and File it in the background. Leave blank to find it on your PATH or in ~/.local/bin."
            value={settings.claude_command ?? ''}
            onChange={(value) => set({ claude_command: value })}
          />
          <Field
            label="Job time limit (minutes)"
            description="A background Claude run that takes longer is stopped and shown as failed."
            value={String(settings.job_timeout_minutes)}
            onChange={(value) => set({ job_timeout_minutes: Number(value) || 10 })}
          />
          <Field
            label="Detail notes folder"
            description="Where Prepare detail writes notes in the vault, one folder per day, until you file them."
            value={settings.detail_notes_subdir ?? ''}
            onChange={(value) => set({ detail_notes_subdir: value })}
          />
          <Field
            label="Model for Prepare detail"
            description="Writes the detailed note. sonnet by default; opus uses your Claude limits much faster, haiku is cheapest. A full model name also works."
            value={settings.job_model_prepare ?? ''}
            onChange={(value) => set({ job_model_prepare: value })}
          />
          <Field
            label="Model for File it"
            description="Picks the folder and moves the note. haiku by default; use sonnet if its choices are poor."
            value={settings.job_model_file ?? ''}
            onChange={(value) => set({ job_model_file: value })}
          />
          <Field
            label="Obsidian MCP server"
            description="The server File it moves notes with, so links and comments follow them. `claude mcp list` shows its name."
            value={settings.obsidian_mcp_server ?? ''}
            onChange={(value) => set({ obsidian_mcp_server: value })}
          />
          <Field
            label="Obsidian address"
            description="Answers while Obsidian runs (the Local REST API plugin). Spyglass checks it before filing, and opens Obsidian when it does not answer."
            value={settings.obsidian_probe_url ?? ''}
            onChange={(value) => set({ obsidian_probe_url: value })}
          />
        </>
      )}

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          className="bg-accent px-4 py-1.5 font-semibold text-card"
          style={{ borderRadius: 'var(--radius-control)' }}
          onClick={save}
        >
          Save settings
        </button>
        {status && <span className="text-muted">{status}</span>}
      </div>
    </div>
  )
}
