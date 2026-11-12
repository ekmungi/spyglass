// VaultSection: where the reader's notes vault is. Claude Code is opened in it to file the queue.
// Spyglass itself never writes into the vault.
import { useId, useState, type FormEvent } from 'react'
import { useFilingConfigured } from '../../state/filingConfigured'
import { Button, SectionHeading } from '../../ui'
import { patchSettings, type SettingsValues } from './api'
import { SaveNote } from './SaveNote'
import { validateVault, type VaultValues } from './validateSettings'
import { useSaveState } from './useSaveState'

export interface VaultSectionProps {
  settings: SettingsValues
  onSaved: (stored: SettingsValues) => void
}

/** The "Vault" group; saves on its own. */
export function VaultSection({ settings, onSaved }: VaultSectionProps) {
  // The sentences about the filing queue are shown only where filing is set up.
  const filingOn = useFilingConfigured()
  const [values, setValues] = useState<VaultValues>({ vault: String(settings.vault_path ?? '') })
  const [showErrors, setShowErrors] = useState(false)
  const save = useSaveState()
  const vaultId = useId()
  const errors = validateVault(values)
  const shown = showErrors ? errors : {}

  const edit = (patch: Partial<VaultValues>) => {
    setValues((current) => ({ ...current, ...patch }))
    save.reset()
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setShowErrors(true)
    if (Object.keys(errors).length > 0) return
    void save.run(async () => {
      onSaved(await patchSettings({ vault_path: values.vault.trim() }))
    })
  }

  return (
    <section aria-labelledby="settings-vault" className="rst-section">
      <SectionHeading id="settings-vault" note="Spyglass never writes into your vault">
        Vault
      </SectionHeading>
      <p className="r-meta">
        Spyglass never writes into the vault itself.
        {filingOn && ' File in vault adds an item to a queue. File now opens one Claude Code session in the vault, where your own vault skills file the items after your yes.'}
      </p>
      <form onSubmit={submit} noValidate>
        <div className="r-field">
          <label htmlFor={vaultId}>Vault folder</label>
          <input
            id={vaultId}
            className="r-input"
            value={values.vault}
            placeholder="The folder your notes live in"
            aria-invalid={shown.vault ? true : undefined}
            onChange={(event) => edit({ vault: event.target.value })}
          />
          <span className="r-meta">Claude Code is opened in this folder.</span>
          {shown.vault && <span className="r-error-text">{shown.vault}</span>}
        </div>
        <div className="rst-actions">
          <Button type="submit" variant="secondary" disabled={save.status === 'saving'}>
            Save vault settings
          </Button>
          <SaveNote state={save} />
        </div>
      </form>
    </section>
  )
}
