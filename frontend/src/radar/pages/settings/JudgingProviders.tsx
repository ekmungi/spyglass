// JudgingProviders: "AI for the daily judging" under the engines list: the AI that judges every
// collected item, and the order of the ones tried when it cannot (out of credit, at its limit, not
// signed in). An AI that is not available is still listed, with its reason, and can still be chosen.
import { useState } from 'react'
import { Button, IconButton, IconRemove, Select } from '../../ui'
import { patchSettings, unconfirmedKeys, type EngineRow, type SettingsValues } from './api'
import { engineFor, joinFallback, MAX_FALLBACK, parseFallback, PROVIDERS, providerName } from './providers'
import { SaveNote } from './SaveNote'
import { useSaveState } from './useSaveState'

export interface JudgingProvidersProps {
  engines: readonly EngineRow[]
  settings: SettingsValues
  /** Called with the settings the service confirmed. */
  onSaved: (stored: SettingsValues) => void
}

/** The saved first choice, falling back to the first provider for a missing or unknown value. */
function savedFirst(settings: SettingsValues): string {
  const stored = String(settings.radar_llm_provider ?? '')
  return PROVIDERS.some((provider) => provider.id === stored) ? stored : PROVIDERS[0].id
}

/** A select for the first choice, chips for the fallback order, and one Save. */
export function JudgingProviders({ engines, settings, onSaved }: JudgingProvidersProps) {
  const firstSaved = savedFirst(settings)
  const orderSaved = parseFallback(settings.radar_llm_fallback).filter((id) => id !== firstSaved)
  const [first, setFirst] = useState(firstSaved)
  const [order, setOrder] = useState(orderSaved)
  const save = useSaveState()
  const dirty = first !== firstSaved || joinFallback(order) !== joinFallback(orderSaved)

  const nameOf = (id: string) => {
    const provider = PROVIDERS.find((entry) => entry.id === id)
    return provider ? providerName(provider, engines) : id
  }
  const optionLabel = (id: string) => {
    const provider = PROVIDERS.find((entry) => entry.id === id)
    const engine = provider ? engineFor(provider, engines) : undefined
    return engine && !engine.available ? `${nameOf(id)} (not available now)` : nameOf(id)
  }
  const remaining = PROVIDERS.filter((provider) => provider.id !== first && !order.includes(provider.id))
  // The reasons shown are only for AIs the reader has put in the list.
  const notes = [first, ...order].flatMap((id) => {
    const provider = PROVIDERS.find((entry) => entry.id === id)
    const engine = provider ? engineFor(provider, engines) : undefined
    return engine && !engine.available && engine.reason ? [{ id, text: `${nameOf(id)}: ${engine.reason}` }] : []
  })

  const edit = (apply: () => void) => {
    apply()
    save.reset()
  }

  const submit = () =>
    save.run(async () => {
      const sent: SettingsValues = { radar_llm_provider: first, radar_llm_fallback: joinFallback(order) }
      const stored = await patchSettings(sent)
      if (unconfirmedKeys(sent, stored).length > 0) {
        throw new Error('Spyglass accepted the request but did not confirm these choices, so they may not have been kept.')
      }
      onSaved(stored)
    })

  return (
    <div className="rst-judging">
      <h3 className="rst-subhead">AI for the daily judging</h3>
      <p className="rst-sub">If the first is out of credit, at its limit or not signed in, the next is used.</p>
      <div className="rst-defaults">
        <Select
          label="First choice"
          value={first}
          onChange={(value) =>
            edit(() => {
              setFirst(value)
              setOrder((current) => current.filter((id) => id !== value))
            })
          }
          options={PROVIDERS.map((provider) => ({ value: provider.id, label: optionLabel(provider.id) }))}
        />
      </div>
      <div className="rst-chain">
        <span className="rst-chain__label">Then try</span>
        {order.length === 0 ? (
          <span className="r-meta">nothing else</span>
        ) : (
          <ol className="rst-chain__list" aria-label="Then try, in order">
            {order.map((id, index) => (
              <li key={id} className="rst-chain__item">
                <span>
                  {index + 1}. {nameOf(id)}
                </span>
                <IconButton label={`Remove ${nameOf(id)} from the list`} icon={<IconRemove size={14} />} onClick={() => edit(() => setOrder(order.filter((entry) => entry !== id)))} />
              </li>
            ))}
          </ol>
        )}
        {order.length < MAX_FALLBACK && remaining.length > 0 && (
          <Select
            label="Add another AI"
            hideLabel
            value=""
            onChange={(value) => value && edit(() => setOrder([...order, value]))}
            options={[{ value: '', label: 'Add another…' }, ...remaining.map((provider) => ({ value: provider.id, label: optionLabel(provider.id) }))]}
          />
        )}
      </div>
      {notes.map((note) => (
        <p key={note.id} className="r-meta rst-reason">
          {note.text}
        </p>
      ))}
      <div className="rst-actions">
        <Button variant="secondary" disabled={!dirty || save.status === 'saving'} onClick={() => void submit()}>
          Save choices
        </Button>
        <SaveNote state={save} />
      </div>
    </div>
  )
}
