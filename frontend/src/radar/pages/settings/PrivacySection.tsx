// PrivacySection: what Spyglass does and does not do with the reader's data. Three plain sentences,
// four switches with one honest line each, then two disclosures: exactly what the AI is sent right
// now, and every place Spyglass connects to. The switches save through PATCH /api/settings.
import { useState } from 'react'
import { Button, SectionHeading, Skeleton } from '../../ui'
import type { PrivacyOutbound, PrivacySwitchKey, PrivacySwitches } from '../../api/types'

import { Switch } from '../sources/Switch'
import { useLoad } from '../sources/useLoad'
import { loadPrivacy, patchSettings, unconfirmedKeys } from './api'
import { PRIVACY_SWITCHES } from './privacySwitches'
import { SaveNote } from './SaveNote'
import { useSaveState } from './useSaveState'

/** A short list of example titles, or a quiet "none". */
function Titles({ heading, titles }: { heading: string; titles: readonly string[] }) {
  return (
    <div>
      <h4 className="rst-minihead">{heading}</h4>
      {titles.length === 0 ? (
        <p className="r-meta">None.</p>
      ) : (
        <ul className="rst-titles">
          {titles.map((title) => (
            <li key={title}>{title}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** The loaded overview: switches and the two disclosures. */
function Overview({ data }: { data: PrivacyOutbound }) {
  const [values, setValues] = useState<PrivacySwitches>(data.switches)
  const save = useSaveState()

  const toggle = (key: PrivacySwitchKey, next: boolean) =>
    save.run(async () => {
      const sent = { [key]: next }
      const stored = await patchSettings(sent)
      if (unconfirmedKeys(sent, stored).length > 0) {
        throw new Error('Spyglass accepted the request but did not confirm this choice, so it may not have been kept.')
      }
      setValues((current) => ({ ...current, [key]: next }))
      return 'Saved.'
    })

  return (
    <>
      <ul className="r-rows rst-switches">
        {PRIVACY_SWITCHES.map(({ key, label }) => (
          <li key={key} className="rst-switch-line">
            <Switch label={label} checked={values[key]} disabled={save.status === 'saving'} onChange={(next) => void toggle(key, next)} />
            <span className="rst-switch-line__text">{label}</span>
          </li>
        ))}
      </ul>
      <SaveNote state={save} />

      <details className="rst-disclosure">
        <summary>What is sent to the AI right now</summary>
        <p className="r-meta">
          Judging and the assistant use {data.model_provider.name} ({data.model_provider.host}). This is the description of you that goes with every
          item, exactly as it is sent.
        </p>
        <label className="r-sr-only" htmlFor="privacy-profile-block">
          The profile text sent to the AI
        </label>
        <textarea id="privacy-profile-block" className="r-textarea rst-sent" readOnly rows={8} value={data.profile_block} />
        {values.privacy_send_examples ? (
          <div className="rst-examples">
            <Titles heading="Titles you liked" titles={data.example_titles.liked} />
            <Titles heading="Titles you disliked" titles={data.example_titles.disliked} />
          </div>
        ) : (
          <p className="r-meta">Titles of items you saved are not sent, because that switch is off.</p>
        )}
      </details>

      <details className="rst-disclosure">
        <summary>Where Spyglass connects</summary>
        <ul className="r-rows">
          {data.destinations.map((destination) => (
            <li key={`${destination.name}-${destination.host}`} className="rst-destination" data-enabled={destination.enabled ? 'true' : 'false'}>
              <div className="rst-destination__head">
                <span className="rst-name">{destination.name}</span>
                <span className="r-meta">{destination.host}</span>
                {destination.carries_secret && <span className="rst-key">carries a key</span>}
                {!destination.enabled && <span className="r-meta">switched off</span>}
              </div>
              <p className="rst-sub">{destination.purpose}</p>
              <p className="r-meta">Sent: {destination.what_is_sent}</p>
            </li>
          ))}
        </ul>
      </details>
    </>
  )
}

/** The Privacy group of the Settings page (no props). */
export function PrivacySection() {
  const privacy = useLoad<PrivacyOutbound | null>((signal) => loadPrivacy(signal))
  let body
  if (privacy.error && !privacy.data) {
    body = (
      <div className="rst-error" role="alert">
        <p className="r-error-text">{privacy.error}</p>
        <Button onClick={privacy.reload}>Try again</Button>
      </div>
    )
  } else if (privacy.loading && privacy.data === null) {
    body = (
      <div aria-busy="true" aria-label="Loading the privacy overview">
        <Skeleton lines={4} />
      </div>
    )
  } else if (privacy.data === null) {
    body = <p className="r-meta">The privacy overview is not available in this copy of Spyglass yet.</p>
  } else {
    body = <Overview data={privacy.data} />
  }

  return (
    <section aria-labelledby="settings-privacy" className="rst-section">
      <SectionHeading id="settings-privacy">Privacy</SectionHeading>
      <p className="rst-privacy-lede">
        Spyglass never signs in anywhere, never sends cookies and never posts anything. Only program code fetches pages, and it only reads. The AI has
        no tools: it cannot browse, open files or run commands.
      </p>
      {body}
      <p className="r-meta rst-privacy-note">The full note is in the application&apos;s docs folder: privacy-and-safety.md.</p>
    </section>
  )
}
