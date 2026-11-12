// DefaultEngine: which engine and model a new conversation with the assistant starts with.
import { useState } from 'react'
import { Button, Select } from '../../ui'
import { patchSettings, unconfirmedKeys, type EngineRow, type SettingsValues } from './api'
import { initialEngine, initialModel } from './defaults'
import { SaveNote } from './SaveNote'
import { useSaveState } from './useSaveState'

export interface DefaultEngineProps {
  engines: readonly EngineRow[]
  /** The saved defaults from the settings (may be empty or missing). */
  saved: { engine: string; model: string }
  /** Called with the values the service confirmed. */
  onSaved: (value: { engine: string; model: string }) => void
}

/** Two selects and a Save button; saves on its own. */
export function DefaultEngine({ engines, saved, onSaved }: DefaultEngineProps) {
  const usable = engines.filter((engine) => engine.available)
  const [engineId, setEngineId] = useState(() => initialEngine(engines, saved.engine))
  const [model, setModel] = useState(() => initialModel(engines.find((engine) => engine.id === initialEngine(engines, saved.engine)), saved.model))
  const save = useSaveState()
  const engine = engines.find((entry) => entry.id === engineId)

  if (usable.length === 0) {
    return <p className="r-meta">No engine is available yet. Add a key or switch one on below, then choose a default here.</p>
  }

  const pickEngine = (id: string) => {
    setEngineId(id)
    setModel(initialModel(engines.find((entry) => entry.id === id), ''))
    save.reset()
  }

  const submit = () =>
    save.run(async () => {
      const sent: SettingsValues = { assist_default_engine: engineId, assist_default_model: model }
      const stored = await patchSettings(sent)
      const missing = unconfirmedKeys(sent, stored)
      if (missing.length > 0) {
        throw new Error('Spyglass accepted the request but did not confirm the new default, so it may not have been kept. Reload the page to check.')
      }
      onSaved({ engine: engineId, model })
    })

  return (
    <div className="rst-defaults">
      <Select
        label="Default engine"
        value={engineId}
        onChange={pickEngine}
        options={usable.map((entry) => ({ value: entry.id, label: entry.label }))}
      />
      <Select
        label="Default model"
        value={model}
        onChange={(value) => {
          setModel(value)
          save.reset()
        }}
        options={(engine?.models ?? []).map((entry) => ({ value: entry.id, label: entry.label }))}
        disabled={!engine || engine.models.length === 0}
      />
      <Button variant="secondary" disabled={save.status === 'saving' || !engineId} onClick={() => void submit()}>
        Save default
      </Button>
      <SaveNote state={save} />
    </div>
  )
}
