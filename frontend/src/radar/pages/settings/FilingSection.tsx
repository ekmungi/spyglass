// FilingSection: how the To file queue reaches the vault. Where background filing is available: off
// (only File now), file first and ask one simple question afterwards, or show the plan first; when a
// background run starts (after the queue has been quiet, and once a day); and the Claude model it
// uses. Saves on its own; the next check (every two minutes) uses the new values, no restart needed.
// Where it is not available (this release) one paragraph says filing runs on File now.
import { useId, useState, type FormEvent } from 'react'
import type { FilingMode } from '../../api/types'
import { useFilingBackgroundAvailable, useFilingConfigured } from '../../state/filingConfigured'
import { Button, SectionHeading } from '../../ui'
import { patchSettings, unconfirmedKeys, type SettingsValues } from './api'
import { SaveNote } from './SaveNote'
import { useSaveState } from './useSaveState'
import { FILING_MODES, MODELS, QUIET_MAX, QUIET_MIN, validateFiling, type FilingValues } from './filingSettings'

export interface FilingSectionProps {
  settings: SettingsValues
  onSaved: (stored: SettingsValues) => void
}

/** What the Filing group says where filing is set up but this version has no background filing. */
export const FILING_MANUAL_ONLY =
  'Filing runs when you click File now, in one Claude Code session that you watch and approve. Background filing is not available in this version.'

/** What the Filing group says where filing is not set up (the whole feature is hidden elsewhere). */
export const FILING_NOT_SET_UP =
  "Filing into a notes vault is an optional integration. It hands the items you choose to your own Claude Code filing skills, which must be named in Spyglass's settings file. See the user guide."

/** The "Filing" group: the controls where filing is set up, one short explanation where it is not. */
export function FilingSection({ settings, onSaved }: FilingSectionProps) {
  const configured = useFilingConfigured()
  const backgroundAvailable = useFilingBackgroundAvailable()
  if (!configured) {
    return (
      <section aria-labelledby="settings-filing" className="rst-section">
        <SectionHeading id="settings-filing">Filing</SectionHeading>
        <p className="r-meta">{FILING_NOT_SET_UP}</p>
      </section>
    )
  }
  if (!backgroundAvailable) {
    return (
      <section aria-labelledby="settings-filing" className="rst-section">
        <SectionHeading id="settings-filing">Filing</SectionHeading>
        <p className="r-meta">{FILING_MANUAL_ONLY}</p>
      </section>
    )
  }
  return <FilingControls settings={settings} onSaved={onSaved} />
}

/** The controls of the "Filing" group; saves on its own. */
function FilingControls({ settings, onSaved }: FilingSectionProps) {
  const stored = String(settings.radar_filing_mode ?? 'off')
  const [values, setValues] = useState<FilingValues>({
    mode: (FILING_MODES.some((mode) => mode.value === stored) ? stored : 'off') as FilingMode,
    quiet: String(settings.radar_filing_quiet_minutes ?? 10),
    daily: String(settings.radar_filing_daily_time ?? '21:00'),
    model: String(settings.radar_filing_model ?? 'sonnet'),
  })
  const [showErrors, setShowErrors] = useState(false)
  const save = useSaveState()
  const quietId = useId()
  const dailyId = useId()
  const modelId = useId()
  const errors = validateFiling(values)
  const shown = showErrors ? errors : {}
  const models = MODELS.some((model) => model.value === values.model) ? MODELS : [...MODELS, { value: values.model, label: values.model }]
  const background = values.mode !== 'off'

  const edit = (patch: Partial<FilingValues>) => {
    setValues((current) => ({ ...current, ...patch }))
    save.reset()
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setShowErrors(true)
    if (Object.keys(errors).length > 0) return
    const sent: SettingsValues = {
      radar_filing_mode: values.mode,
      radar_filing_quiet_minutes: Number(values.quiet),
      radar_filing_daily_time: values.daily,
      radar_filing_model: values.model,
    }
    void save.run(async () => {
      const reply = await patchSettings(sent)
      if (unconfirmedKeys(sent, reply).length > 0) {
        throw new Error('Spyglass accepted the request but did not confirm these settings, so they may not have been kept.')
      }
      onSaved(reply)
      return 'Saved. The next check uses these settings.'
    })
  }

  return (
    <section aria-labelledby="settings-filing" className="rst-section">
      <SectionHeading id="settings-filing">Filing</SectionHeading>
      <form onSubmit={submit} noValidate>
        <fieldset className="rst-fonts">
          <legend className="rst-fonts__legend">How queued items reach your vault</legend>
          <div className="rst-filing-modes">
            {FILING_MODES.map((mode) => (
              <label key={mode.value} className="rst-radio rst-filing-mode">
                <input type="radio" name="filing-mode" value={mode.value} checked={values.mode === mode.value} onChange={() => edit({ mode: mode.value })} />
                <span>
                  <span className="rst-filing-mode__label">{mode.label}</span>
                  <span className="r-meta rst-filing-mode__sentence">{mode.sentence}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="rst-grid">
          <div className="r-field">
            <label htmlFor={quietId}>Start after a quiet queue of (minutes)</label>
            <input id={quietId} className="r-input" type="number" inputMode="numeric" min={QUIET_MIN} max={QUIET_MAX} step={1} value={values.quiet} disabled={!background} aria-invalid={shown.quiet ? true : undefined} onChange={(event) => edit({ quiet: event.target.value })} />
            {shown.quiet && <span className="r-error-text">{shown.quiet}</span>}
          </div>
          <div className="r-field">
            <label htmlFor={dailyId}>And once a day at</label>
            <input id={dailyId} className="r-input" type="time" value={values.daily} disabled={!background} aria-invalid={shown.daily ? true : undefined} onChange={(event) => edit({ daily: event.target.value })} />
            {shown.daily && <span className="r-error-text">{shown.daily}</span>}
          </div>
          <div className="r-field">
            <label htmlFor={modelId}>Claude model</label>
            <select id={modelId} className="r-input" value={values.model} disabled={!background} onChange={(event) => edit({ model: event.target.value })}>
              {models.map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="r-meta rst-filing-note">
          A background run uses your own Claude Code with your vault skills, in your vault folder. It may create notes and add links; it never deletes, moves or renames anything.
        </p>
        <div className="rst-actions">
          <Button type="submit" variant="secondary" disabled={save.status === 'saving'}>
            Save filing settings
          </Button>
          <SaveNote state={save} />
        </div>
      </form>
    </section>
  )
}
