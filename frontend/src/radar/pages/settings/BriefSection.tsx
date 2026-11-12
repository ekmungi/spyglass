// BriefSection: when the daily brief is made, in which time zone, and how often Spyglass collects.
import { useId, useState, type FormEvent } from 'react'
import { Button, SectionHeading } from '../../ui'
import { patchSettings, unconfirmedKeys, type SettingsValues } from './api'
import { SaveNote } from './SaveNote'
import { knownZones, MAX_HOURS, MIN_HOURS, validateBrief, type BriefValues } from './validateSettings'
import { useSaveState } from './useSaveState'

export interface BriefSectionProps {
  settings: SettingsValues
  onSaved: (stored: SettingsValues) => void
}

/** The "Daily brief" group; saves on its own. */
export function BriefSection({ settings, onSaved }: BriefSectionProps) {
  const initial = {
    time: String(settings.radar_brief_time ?? ''),
    zone: String(settings.radar_timezone ?? ''),
    hours: settings.radar_collect_hours === undefined || settings.radar_collect_hours === null ? '' : String(settings.radar_collect_hours),
  }
  const [values, setValues] = useState<BriefValues>(initial)
  const [showErrors, setShowErrors] = useState(false)
  const save = useSaveState()
  const timeId = useId()
  const zoneId = useId()
  const hoursId = useId()
  const zoneList = useId()
  const errors = validateBrief(values)
  const shown = showErrors ? errors : {}
  const zones = knownZones()

  const edit = (patch: Partial<BriefValues>) => {
    setValues((current) => ({ ...current, ...patch }))
    save.reset()
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setShowErrors(true)
    if (Object.keys(errors).length > 0) return
    const sent: SettingsValues = { radar_brief_time: values.time, radar_timezone: values.zone.trim(), radar_collect_hours: Number(values.hours) }
    void save.run(async () => {
      const stored = await patchSettings(sent)
      const missing = unconfirmedKeys(sent, stored)
      if (missing.length > 0) {
        throw new Error('Spyglass accepted the request but did not confirm these settings, so they may not have been kept.')
      }
      onSaved(stored)
      return 'Saved. Close and start Spyglass again for the new times to apply.'
    })
  }

  return (
    <section aria-labelledby="settings-brief" className="rst-section">
      <SectionHeading id="settings-brief">Daily brief</SectionHeading>
      <form onSubmit={submit} noValidate>
        <div className="rst-grid">
          <div className="r-field">
            <label htmlFor={timeId}>Brief time</label>
            <input
              id={timeId}
              className="r-input"
              type="time"
              value={values.time}
              aria-invalid={shown.time ? true : undefined}
              onChange={(event) => edit({ time: event.target.value })}
            />
            {shown.time && <span className="r-error-text">{shown.time}</span>}
          </div>
          <div className="r-field">
            <label htmlFor={zoneId}>Time zone</label>
            <input
              id={zoneId}
              className="r-input"
              list={zoneList}
              value={values.zone}
              placeholder="This computer's time zone"
              aria-invalid={shown.zone ? true : undefined}
              onChange={(event) => edit({ zone: event.target.value })}
            />
            <datalist id={zoneList}>
              {zones.map((zone) => (
                <option key={zone} value={zone} />
              ))}
            </datalist>
            {shown.zone && <span className="r-error-text">{shown.zone}</span>}
          </div>
          <div className="r-field">
            <label htmlFor={hoursId}>Collect every (hours)</label>
            <input
              id={hoursId}
              className="r-input"
              type="number"
              inputMode="decimal"
              min={MIN_HOURS}
              max={MAX_HOURS}
              step={0.25}
              value={values.hours}
              aria-invalid={shown.hours ? true : undefined}
              onChange={(event) => edit({ hours: event.target.value })}
            />
            {shown.hours && <span className="r-error-text">{shown.hours}</span>}
          </div>
        </div>
        <div className="rst-actions">
          <Button type="submit" variant="secondary" disabled={save.status === 'saving'}>
            Save brief settings
          </Button>
          <SaveNote state={save} />
        </div>
      </form>
    </section>
  )
}
