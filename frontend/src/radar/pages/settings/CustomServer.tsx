// CustomServer: add a server of your own that speaks the same protocol as OpenAI (for example one on your network).
import { useId, useState, type FormEvent } from 'react'
import { Button } from '../../ui'
import { configureEngine, type EngineRow } from './api'
import { SaveNote } from './SaveNote'
import { slugify } from './slug'
import { useSaveState } from './useSaveState'

export interface CustomServerProps {
  existingIds: readonly string[]
  onAdded: (engine: EngineRow) => void
}

/** A quiet "Add a custom server" link that opens a two-field form. */
export function CustomServer({ existingIds, onAdded }: CustomServerProps) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const save = useSaveState()
  const nameId = useId()
  const addressId = useId()

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void save.run(async () => {
      const id = `custom-${slugify(name)}`
      if (!slugify(name)) throw new Error('Give the server a name made of letters or numbers.')
      if (!/^https?:\/\/\S+$/.test(address.trim())) throw new Error('The address must start with http:// or https://')
      if (existingIds.includes(id)) throw new Error('A server with that name already exists.')
      onAdded(await configureEngine(id, { base_url: address.trim(), label: name.trim() }))
      setName('')
      setAddress('')
      setOpen(false)
      return 'Server added.'
    })
  }

  if (!open) {
    return (
      <div className="rst-inline">
        <Button variant="quiet" size="sm" onClick={() => setOpen(true)}>
          Add a custom server
        </Button>
        <SaveNote state={save} />
      </div>
    )
  }
  return (
    <form className="rst-custom" onSubmit={submit} noValidate>
      <div className="r-field">
        <label htmlFor={nameId}>Server name</label>
        <input id={nameId} className="r-input" value={name} onChange={(event) => setName(event.target.value)} />
      </div>
      <div className="r-field">
        <label htmlFor={addressId}>Server address</label>
        <input id={addressId} className="r-input" value={address} placeholder="http://192.168.1.20:8000/v1" onChange={(event) => setAddress(event.target.value)} />
      </div>
      <div className="rst-inline">
        <Button type="submit" variant="secondary" disabled={save.status === 'saving'}>
          Add server
        </Button>
        <Button variant="quiet" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <SaveNote state={save} />
      </div>
    </form>
  )
}
