// Shared builders for the Watch page tests: a register entry, a recent item and a small register, and
// a way to clear the toasts an earlier test left on screen.
import { dismissToast, subscribeToasts, type ToastMessage } from '../../ui/toastStore'
import type { WatchEntry, WatchRegister } from './api'

/** Dismiss every toast still queued, so a test never finds an earlier test's message or Undo. */
export function clearToasts(): void {
  let queued: readonly ToastMessage[] = []
  // Subscribing hands over the current queue at once; nothing needs to stay subscribed.
  subscribeToasts((list) => {
    queued = list
  })()
  queued.forEach((item) => dismissToast(item.id))
}

const DAY = 24 * 60 * 60 * 1000

/** A followed register entry; override any field. */
export function entry(over: Partial<WatchEntry> & { id: number; name: string }): WatchEntry {
  return {
    kind: 'company',
    category: 'Imaging AI',
    topic: null,
    aliases: [],
    website: null,
    status: 'active',
    section: '',
    count: 0,
    why: null,
    added_via: 'seed',
    last_hit_at: null,
    recent: [],
    ...over,
  }
}

/** A recent item as the register lists it under a name. */
export function recentItem(id: number, headline: string) {
  return { id, title: headline, headline, published_at: new Date().toISOString(), fetched_at: new Date().toISOString() }
}

/** Two groups: Imaging AI (two active names, 3 items this week) and Regulators (one muted name, so paused), plus one suggestion; no profile sections and nothing rejected. */
export function register(): WatchRegister {
  return {
    categories: [
      {
        name: 'Imaging AI',
        week_count: 3,
        paused: false,
        entities: [
          entry({ id: 1, name: 'Alpha Scopes', why: 'Makes polyp detection software.', week_count: 0 }),
          entry({
            id: 2,
            name: 'Zeta Vision',
            why: 'Cleared a new endoscopy model.',
            week_count: 3,
            last_hit_at: new Date(Date.now() - 2 * DAY).toISOString(),
            recent: [recentItem(55, 'Zeta Vision wins clearance') as never],
          }),
        ],
      },
      {
        name: 'Regulators',
        week_count: 0,
        paused: true,
        entities: [entry({ id: 3, name: 'FDA', kind: 'regulator', category: 'Regulators', status: 'muted', week_count: 0 })],
      },
    ],
    suggested: [entry({ id: 9, name: 'Gamma Labs', kind: 'lab', status: 'suggested', topic: 'agents', why: 'Builds agent tooling.' })],
    rejected: [],
    sections: [],
  }
}
