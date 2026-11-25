// useWatchLayout: lay the Watch page out once per load and keep that layout. A chip click switches
// one name between watched and paused in place, asks the server, and puts the earlier look back if
// the server refuses. A name switched on this visit keeps its place, and its look, when new data
// arrives, until the page calls `restructure` for an action that changes the structure.
import { useState } from 'react'
import { errorMessage } from '../../api/errors'
import type { WatchStatus } from '../../api/types'
import { toast } from '../../ui'
import { changeEntry, type WatchEntry, type WatchRegister } from './api'
import { layoutRegister, registerWithStatuses, withStatuses, type StatusById, type WatchLayout } from './organize'

export interface WatchLayoutState {
  /** The layout of the last load with the looks switched since; null before the first load. */
  layout: WatchLayout | null
  /** Names whose change is on the way to the server. */
  switching: ReadonlySet<number>
  /** Switch one name: watched becomes paused, paused becomes watched. */
  toggle: (entity: WatchEntry) => void
  /**
   * Call before an action that changes the structure (add, remove, move, a group action, an applied
   * review): its answer then lays the names switched on this visit out where their status puts them,
   * except those still on their way to the server, which keep their place and look.
   */
  restructure: () => void
}

/** One name switched on this visit. */
interface Switch {
  /** The status that decides where the name is shown: where the page put it before the first switch. */
  place: WatchStatus
  /** The status the chip shows. */
  look: WatchStatus
  /** Its request is on the way. */
  pending: boolean
}

type Switches = ReadonlyMap<number, Switch>

interface View {
  /** The answer the layout was made from. */
  load: WatchRegister | null
  layout: WatchLayout | null
  switches: Switches
}

/** One field of every switch, by name id. */
function pick(switches: Switches, field: 'place' | 'look'): StatusById {
  return new Map([...switches].map(([id, item]) => [id, item[field]]))
}

/** Lay `data` out with each switched name in its kept place and with its current look. */
function layoutFor(data: WatchRegister | null, switches: Switches): WatchLayout | null {
  if (!data) return null
  return withStatuses(layoutRegister(registerWithStatuses(data, pick(switches, 'place'))), pick(switches, 'look'))
}

/** Where the layout shows a name: "active" in a group, "muted" in the Paused list. */
function placeIn(layout: WatchLayout | null, id: number): WatchStatus | undefined {
  if (layout?.groups.some((group) => group.entities.some((entity) => entity.id === id))) return 'active'
  if (layout?.paused.some((name) => name.entity.id === id)) return 'muted'
  return undefined
}

/** The toast after a switch: what changes for the daily search. */
function switchedText(name: string, to: WatchStatus): string {
  return to === 'active'
    ? `Watching ${name} again. Spyglass searches for it from the next run.`
    : `Paused ${name}. Spyglass stops searching for it. Nothing is deleted.`
}

/**
 * The layout for `data` and the chip switch. A new answer is laid out afresh, keeping the switched
 * names in place. `remember` keeps the answer shown on the next visit in step with each confirmed switch.
 */
export function useWatchLayout(data: WatchRegister | null, remember: (update: (current: WatchRegister) => WatchRegister) => void): WatchLayoutState {
  const [view, setView] = useState<View>({ load: null, layout: null, switches: new Map() })
  // A new answer is laid out during this render, before anything is drawn from the old layout.
  if (view.load !== data) setView({ ...view, load: data, layout: layoutFor(data, view.switches) })
  const switching: ReadonlySet<number> = new Set([...view.switches].filter(([, item]) => item.pending).map(([id]) => id))

  /** Record a name's look (and, at its first switch, its place) and show the look at once. */
  const setLook = (id: number, from: WatchStatus, look: WatchStatus, pending: boolean) =>
    setView((current) => {
      const place = current.switches.get(id)?.place ?? placeIn(current.layout, id) ?? from
      const switches = new Map(current.switches).set(id, { place, look, pending })
      return { ...current, switches, layout: current.layout && withStatuses(current.layout, new Map([[id, look]])) }
    })

  /**
   * Watch or pause one name: the chip changes at once, then the server is asked. A failure puts the
   * earlier look back and says why; a success says what changed and offers Undo (`announce`).
   */
  const switchName = async (entity: WatchEntry, to: WatchStatus, announce = true) => {
    const from = entity.status
    setLook(entity.id, from, to, true)
    try {
      await changeEntry(entity.id, { status: to })
      setLook(entity.id, from, to, false)
      remember((current) => registerWithStatuses(current, new Map([[entity.id, to]])))
      if (announce) {
        toast(switchedText(entity.name, to), { action: { label: 'Undo', onClick: () => void switchName({ ...entity, status: to }, from, false) } })
      }
    } catch (cause) {
      setLook(entity.id, from, from, false)
      toast(errorMessage(cause), { tone: 'error' })
    }
  }

  const toggle = (entity: WatchEntry) => {
    if (!switching.has(entity.id)) void switchName(entity, entity.status === 'active' ? 'muted' : 'active')
  }

  const restructure = () =>
    setView((current) => ({ ...current, switches: new Map([...current.switches].filter(([, item]) => item.pending)) }))

  return { layout: view.layout, switching, toggle, restructure }
}
