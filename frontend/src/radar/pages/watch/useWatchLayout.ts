// useWatchLayout: lay the Watch page out once per load and keep that layout. A chip click switches
// one name between watched and paused in place, asks the server, and puts the earlier look back if
// the server refuses, so no chip moves or disappears until the next load.
import { useState } from 'react'
import { errorMessage } from '../../api/errors'
import type { WatchStatus } from '../../api/types'
import { toast } from '../../ui'
import { changeEntry, type WatchEntry, type WatchRegister } from './api'
import { layoutRegister, registerWithStatus, withStatus, type WatchLayout } from './organize'

export interface WatchLayoutState {
  /** The layout of the last load with the looks switched since; null before the first load. */
  layout: WatchLayout | null
  /** Names whose change is on the way to the server. */
  switching: ReadonlySet<number>
  /** Switch one name: watched becomes paused, paused becomes watched. */
  toggle: (entity: WatchEntry) => void
}

/** The toast after a switch: what changes for the daily search. */
function switchedText(name: string, to: WatchStatus): string {
  return to === 'active'
    ? `Watching ${name} again. Spyglass searches for it from the next run.`
    : `Paused ${name}. Spyglass stops searching for it. Nothing is deleted.`
}

/** A copy of the set without `id`. */
function without(ids: ReadonlySet<number>, id: number): ReadonlySet<number> {
  const next = new Set(ids)
  next.delete(id)
  return next
}

/**
 * The layout for `data` (a new load or a replaced register lays the page out afresh) and the chip
 * switch. `remember` keeps the answer shown on the next visit in step with each confirmed switch.
 */
export function useWatchLayout(data: WatchRegister | null, remember: (update: (current: WatchRegister) => WatchRegister) => void): WatchLayoutState {
  const [view, setView] = useState<{ load: WatchRegister | null; layout: WatchLayout | null }>({ load: null, layout: null })
  // A new answer is laid out during this render, before anything is drawn from the old layout.
  if (view.load !== data) setView({ load: data, layout: data ? layoutRegister(data) : null })
  const [switching, setSwitching] = useState<ReadonlySet<number>>(() => new Set())

  /** Change one name's look in the layout on screen, leaving every chip where it is. */
  const patchStatus = (id: number, status: WatchStatus) =>
    setView((current) => (current.layout ? { ...current, layout: withStatus(current.layout, id, status) } : current))

  /**
   * Watch or pause one name: the chip changes at once, then the server is asked. A failure puts the
   * earlier look back and says why; a success says what changed and offers Undo (`announce`).
   */
  const switchName = async (entity: WatchEntry, to: WatchStatus, announce = true) => {
    const from = entity.status
    patchStatus(entity.id, to)
    setSwitching((ids) => new Set(ids).add(entity.id))
    try {
      await changeEntry(entity.id, { status: to })
      remember((current) => registerWithStatus(current, entity.id, to))
      if (announce) {
        toast(switchedText(entity.name, to), { action: { label: 'Undo', onClick: () => void switchName({ ...entity, status: to }, from, false) } })
      }
    } catch (cause) {
      patchStatus(entity.id, from)
      toast(errorMessage(cause), { tone: 'error' })
    } finally {
      setSwitching((ids) => without(ids, entity.id))
    }
  }

  const toggle = (entity: WatchEntry) => {
    if (!switching.has(entity.id)) void switchName(entity, entity.status === 'active' ? 'muted' : 'active')
  }

  return { layout: view.layout, switching, toggle }
}
