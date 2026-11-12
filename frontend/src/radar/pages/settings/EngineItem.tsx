// EngineItem: one assistant engine: whether it works, and the one thing to do about it (paste a
// key, switch it on, or set its address). A pasted key is sent once and is never shown again.
import { useId, useState } from 'react'
import { Button } from '../../ui'
import { Switch } from '../sources/Switch'
import { configureEngine, removeEngine, type EngineRow } from './api'
import { SaveNote } from './SaveNote'
import { useSaveState } from './useSaveState'

export interface EngineItemProps {
  engine: EngineRow
  /** The engine as the service now describes it. */
  onChange: (engine: EngineRow) => void
  /** A custom server was removed. */
  onRemoved: (id: string) => void
}

/** A row in the AI engines list. */
export function EngineItem({ engine, onChange, onRemoved }: EngineItemProps) {
  const keyId = useId()
  const urlId = useId()
  const [key, setKey] = useState('')
  const [replacing, setReplacing] = useState(false)
  const [confirmingRemove, setConfirmingRemove] = useState(false)
  const [url, setUrl] = useState(engine.base_url ?? '')
  const keySave = useSaveState()
  const urlSave = useSaveState()
  const switchSave = useSaveState()
  const removeSave = useSaveState()
  // The service says whether a key is needed; a hosted (api) engine without that field is assumed to need one.
  const needsKey = engine.needs_key ?? engine.kind === 'api'
  const usesAddress = engine.kind === 'local' || engine.kind === 'custom'
  // A command-line engine (any id, today or later) has an enable switch and nothing to paste: it
  // uses the program and sign-in already on this computer. An engine that reports an enabled flag
  // but needs no key and no address is shown the same way.
  const isCli = engine.kind === 'cli' || (!needsKey && !usesAddress && typeof engine.enabled === 'boolean')
  const fromEnvironment = engine.key_source === 'env'
  const showKeyField = needsKey && !fromEnvironment && (!engine.has_key || replacing)

  const storeKey = async () => {
    const secret = key.trim()
    if (!secret) return
    const ok = await keySave.run(async () => {
      const updated = await configureEngine(engine.id, { api_key: secret })
      onChange({ ...updated, has_key: true })
      return 'Saved to this computer’s key store.'
    })
    // Clear the field whatever happened: the pasted key is never kept on screen.
    setKey('')
    if (ok) setReplacing(false)
  }

  const removeKey = () =>
    keySave.run(async () => {
      const updated = await configureEngine(engine.id, { api_key: '' })
      onChange({ ...updated, has_key: false })
      return 'Key removed.'
    })

  const toggle = (enabled: boolean) =>
    switchSave.run(async () => {
      onChange(await configureEngine(engine.id, { enabled }))
      return enabled ? 'Switched on.' : 'Switched off.'
    })

  const saveAddress = () => {
    const address = url.trim()
    if (!/^https?:\/\/\S+$/.test(address)) return urlSave.run(async () => {
        throw new Error('The address must start with http:// or https://')
      })
    return urlSave.run(async () => {
      onChange(await configureEngine(engine.id, { base_url: address }))
      return 'Address saved.'
    })
  }

  const remove = () => {
    if (!confirmingRemove) {
      setConfirmingRemove(true)
      return
    }
    return removeSave.run(async () => {
      await removeEngine(engine.id)
      onRemoved(engine.id)
    })
  }

  return (
    <li className="rst-engine">
      <div className="rst-engine__head">
        <span className="rst-name">{engine.label}</span>
        <span className={engine.available ? 'rst-ok' : 'r-meta'}>{engine.available ? 'Available' : 'Not configured'}</span>
      </div>
      {!engine.available && engine.reason && <p className="r-meta rst-reason">{engine.reason}</p>}

      {isCli && (
        <div className="rst-switch-row">
          <Switch label={`Use ${engine.label}`} checked={engine.enabled === true} disabled={switchSave.status === 'saving'} onChange={(next) => void toggle(next)} />
          <span className="rst-sub">Uses the program and sign-in already on this computer, for your personal use only.</span>
          <SaveNote state={switchSave} />
        </div>
      )}

      {needsKey && fromEnvironment && (
        <p className="r-meta">The key is read from this computer&apos;s environment settings and cannot be changed here.</p>
      )}
      {needsKey && !fromEnvironment && engine.has_key && !replacing && (
        <div className="rst-inline">
          <span className="rst-ok">Key stored</span>
          <Button variant="quiet" size="sm" onClick={() => setReplacing(true)}>
            Replace key
          </Button>
          <Button variant="quiet" size="sm" onClick={() => void removeKey()}>
            Remove key
          </Button>
          <SaveNote state={keySave} />
        </div>
      )}
      {showKeyField && (
        <div className="rst-field-row">
          <div className="r-field">
            <label htmlFor={keyId}>API key for {engine.label}</label>
            <input
              id={keyId}
              className="r-input"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={key}
              onChange={(event) => setKey(event.target.value)}
            />
          </div>
          <Button variant="secondary" disabled={!key.trim() || keySave.status === 'saving'} onClick={() => void storeKey()}>
            Save key
          </Button>
          {replacing && (
            <Button variant="quiet" onClick={() => { setReplacing(false); setKey('') }}>
              Cancel
            </Button>
          )}
          <SaveNote state={keySave} />
        </div>
      )}

      {usesAddress && (
        <div className="rst-field-row">
          <div className="r-field">
            <label htmlFor={urlId}>Server address for {engine.label}</label>
            <input id={urlId} className="r-input" value={url} placeholder="http://localhost:1234/v1" onChange={(event) => { setUrl(event.target.value); urlSave.reset() }} />
          </div>
          <Button variant="secondary" disabled={urlSave.status === 'saving' || url.trim() === (engine.base_url ?? '')} onClick={() => void saveAddress()}>
            Save address
          </Button>
          <SaveNote state={urlSave} />
        </div>
      )}

      {engine.custom && (
        <div className="rst-inline">
          <Button variant="quiet" size="sm" onClick={() => void remove()} disabled={removeSave.status === 'saving'}>
            {confirmingRemove ? 'Click again to remove it and its key' : 'Remove this server'}
          </Button>
          <SaveNote state={removeSave} />
        </div>
      )}
    </li>
  )
}
