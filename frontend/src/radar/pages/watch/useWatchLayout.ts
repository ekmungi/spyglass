// useWatchLayout: lay the Watch page out once per load and keep that layout. A chip click changes one
// name's status in place (watched, paused, a suggestion watched, rejected or taken back), asks the
// server, and puts the earlier look back if the server refuses. A name changed on this visit keeps its
// place, and its look, when new data arrives, until the page calls `restructure` for an action that
// changes the structure.
import { useEffect, useRef, useState } from 'react'
import { errorMessage } from '../../api/errors'
import type { SuggestionStatus, WatchStatus } from '../../api/types'
import { toast } from '../../ui'
import { changeEntry, setSuggestionStatus, type WatchEntry, type WatchRegister } from './api'
import { layoutRegister, registerWithStatuses, withStatuses, type StatusById, type WatchLayout } from './organize'

export interface WatchLayoutState {
  /** The layout of the last load with the looks changed since; null before the first load. */
  layout: WatchLayout | null
  /** Names whose change is on the way to the server. */
  switching: ReadonlySet<number>
  /** Switch one watched name: watched becomes paused, paused becomes watched. */
  toggle: (entity: WatchEntry) => void
  /**
   * Give one name a new status in place; `done` is the toast after the server agrees, which offers
   * Undo. Ignored while the name's earlier change is on its way.
   */
  change: (entity: WatchEntry, to: WatchStatus, done: string) => void
  /**
   * Move many suggestions between "suggested" and "rejected" in one request; `done` makes the toast
   * from the number that really changed, and its Undo moves those back.
   */
  changeMany: (entities: readonly WatchEntry[], to: SuggestionStatus, done: (count: number) => string) => void
  /**
   * Call before an action that changes the structure (add, remove, move, a group action, an applied
   * review): its answer then lays the names changed on this visit out where their status puts them,
   * except those still on their way to the server, which keep their place and look.
   */
  restructure: () => void
}

/** One name changed on this visit. */
interface Switch {
  /** The status that decides where the name is shown: where the page put it before the first change. */
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

/** Lay `data` out with each changed name in its kept place and with its current look. */
function layoutFor(data: WatchRegister | null, switches: Switches): WatchLayout | null {
  if (!data) return null
  return withStatuses(layoutRegister(registerWithStatuses(data, pick(switches, 'place'))), pick(switches, 'look'))
}

/** Where the layout shows a name: a group, the Paused list, a suggestion row or the Not of interest list. */
function placeIn(layout: WatchLayout | null, id: number): WatchStatus | undefined {
  const has = (list: readonly WatchEntry[]) => list.some((entity) => entity.id === id)
  if (!layout) return undefined
  if (layout.groups.some((group) => has(group.entities))) return 'active'
  if (layout.paused.some((name) => name.entity.id === id)) return 'muted'
  if (layout.rows.some((row) => has(row.entities))) return 'suggested'
  if (has(layout.rejected)) return 'rejected'
  return undefined
}

/** The look the layout shows for a name now, wherever it is shown; undefined when it is not shown. */
function lookIn(layout: WatchLayout | null, id: number): WatchStatus | undefined {
  if (!layout) return undefined
  const shown = [
    ...layout.groups.flatMap((group) => group.entities),
    ...layout.paused.map((name) => name.entity),
    ...layout.rows.flatMap((row) => row.entities),
    ...layout.rejected,
  ]
  return shown.find((entity) => entity.id === id)?.status
}

/** The toast after a watched name is switched: what changes for the daily search. */
function switchedText(name: string, to: WatchStatus): string {
  return to === 'active'
    ? `Watching ${name} again. Spyglass searches for it from the next run.`
    : `Paused ${name}. Spyglass stops searching for it. Nothing is deleted.`
}

/**
 * The layout for `data` and the chip changes. A new answer is laid out afresh, keeping the changed
 * names in place. `remember` keeps the answer shown on the next visit in step with each confirmed change.
 */
export function useWatchLayout(data: WatchRegister | null, remember: (update: (current: WatchRegister) => WatchRegister) => void): WatchLayoutState {
  const [view, setView] = useState<View>({ load: null, layout: null, switches: new Map() })
  // A new answer is laid out during this render, before anything is drawn from the old layout.
  if (view.load !== data) setView({ ...view, load: data, layout: layoutFor(data, view.switches) })
  const switching: ReadonlySet<number> = new Set([...view.switches].filter(([, item]) => item.pending).map(([id]) => id))
  // The view as last drawn, for an Undo clicked long after its toast appeared.
  const latest = useRef(view)
  useEffect(() => {
    latest.current = view
  })

  /**
   * True when a name still shows `look` and has no change on its way. An Undo acts only on such names:
   * a name the reader changed again since its toast appeared is left as it is now.
   */
  const stillShows = (id: number, look: WatchStatus) => lookIn(latest.current.layout, id) === look && !latest.current.switches.get(id)?.pending

  /**
   * Record each name's look (and, at its first change, its place) and show the looks at once. Each
   * entity carries the look it had before this change, which is its place when the layout lacks it.
   */
  const setLooks = (entities: readonly WatchEntry[], lookOf: (entity: WatchEntry) => WatchStatus, pending: boolean) =>
    setView((current) => {
      const switches = new Map(current.switches)
      const looks = new Map<number, WatchStatus>()
      for (const entity of entities) {
        const place = current.switches.get(entity.id)?.place ?? placeIn(current.layout, entity.id) ?? entity.status
        switches.set(entity.id, { place, look: lookOf(entity), pending })
        looks.set(entity.id, lookOf(entity))
      }
      return { ...current, switches, layout: current.layout && withStatuses(current.layout, looks) }
    })

  /**
   * Give one name a new status: the chip changes at once, then the server is asked. A failure puts the
   * earlier look back and says why; a success shows `done` with Undo, when given. The Undo does nothing
   * when the name no longer shows `to`.
   */
  const switchName = async (entity: WatchEntry, to: WatchStatus, done?: string) => {
    const from = entity.status
    setLooks([entity], () => to, true)
    try {
      await changeEntry(entity.id, { status: to })
      setLooks([entity], () => to, false)
      remember((current) => registerWithStatuses(current, new Map([[entity.id, to]])))
      const undo = () => {
        if (stillShows(entity.id, to)) void switchName({ ...entity, status: to }, from)
      }
      if (done) toast(done, { action: { label: 'Undo', onClick: undo } })
    } catch (cause) {
      setLooks([entity], () => from, false)
      toast(errorMessage(cause), { tone: 'error' })
    }
  }

  /**
   * Move many suggestions to `to` in one request; each entity carries its look just before it. Only the
   * names whose status really changed take the new look; the others, and all of them on a failure, keep
   * that earlier look. The Undo takes back only the names that still show `to` when it is clicked.
   */
  const switchMany = async (entities: readonly WatchEntry[], to: SuggestionStatus, done?: (count: number) => string) => {
    setLooks(entities, () => to, true)
    try {
      const { changed } = await setSuggestionStatus(
        entities.map((entity) => entity.id),
        to,
      )
      const moved = new Set(changed)
      setLooks(entities, (entity) => (moved.has(entity.id) ? to : entity.status), false)
      remember((current) => registerWithStatuses(current, new Map(changed.map((id) => [id, to]))))
      if (done) {
        const back = entities.filter((entity) => moved.has(entity.id)).map((entity) => ({ ...entity, status: to }))
        const undoTo: SuggestionStatus = to === 'rejected' ? 'suggested' : 'rejected'
        const undo = () => {
          const still = back.filter((entity) => stillShows(entity.id, to))
          if (still.length > 0) void switchMany(still, undoTo)
        }
        toast(done(back.length), { action: { label: 'Undo', onClick: undo } })
      }
    } catch (cause) {
      setLooks(entities, (entity) => entity.status, false)
      toast(errorMessage(cause), { tone: 'error' })
    }
  }

  const change = (entity: WatchEntry, to: WatchStatus, done: string) => {
    if (!switching.has(entity.id)) void switchName(entity, to, done)
  }

  const toggle = (entity: WatchEntry) => {
    const to = entity.status === 'active' ? 'muted' : 'active'
    change(entity, to, switchedText(entity.name, to))
  }

  const changeMany = (entities: readonly WatchEntry[], to: SuggestionStatus, done: (count: number) => string) => {
    const free = entities.filter((entity) => !switching.has(entity.id))
    if (free.length > 0) void switchMany(free, to, done)
  }

  const restructure = () =>
    setView((current) => ({ ...current, switches: new Map([...current.switches].filter(([, item]) => item.pending)) }))

  return { layout: view.layout, switching, toggle, change, changeMany, restructure }
}
