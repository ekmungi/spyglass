// Pure helpers for the review panel: the checklist rows for each kind of proposal, and the apply body for the ticked ones.
import type { WatchApplyBody, WatchReview } from '../../api/types'

export interface ReviewRow {
  key: string
  label: string
  meta?: string
  reason: string
}

/** Every row of the review, by kind, with the key the tick set uses. */
export function reviewRows(review: WatchReview): { kind: string; legend: string; hint?: string; rows: ReviewRow[] }[] {
  const named = (kind: 'pause' | 'remove') =>
    review[kind].map((p) => ({ key: `${kind}:${p.id}`, label: p.name, meta: p.category, reason: p.reason }))
  return [
    { kind: 'pause', legend: 'Pause', hint: 'Paused names stay on the list and can be resumed.', rows: named('pause') },
    { kind: 'remove', legend: 'Remove', hint: 'You can undo a removal right after.', rows: named('remove') },
    { kind: 'add', legend: 'Add', rows: review.add.map((a, i) => ({ key: `add:${i}`, label: a.name, meta: a.category, reason: a.why })) },
    {
      kind: 'regroup',
      legend: 'Move to another group',
      rows: review.regroup.map((r) => ({ key: `regroup:${r.id}`, label: `${r.name} to ${r.to}`, meta: `from ${r.from}`, reason: r.reason })),
    },
    {
      kind: 'merge',
      legend: 'Merge groups',
      rows: review.merge_groups.map((m, i) => ({
        key: `merge:${i}`,
        label: `${m.from} into ${m.to}`,
        meta: `${m.count} ${m.count === 1 ? 'name' : 'names'}`,
        reason: m.reason,
      })),
    },
  ].filter((section) => section.rows.length > 0)
}

/** The request body for exactly the ticked rows. */
export function selectionBody(review: WatchReview, ticked: ReadonlySet<string>): WatchApplyBody {
  return {
    pause: review.pause.filter((p) => ticked.has(`pause:${p.id}`)).map((p) => p.id),
    remove: review.remove.filter((p) => ticked.has(`remove:${p.id}`)).map((p) => p.id),
    add: review.add.filter((_, i) => ticked.has(`add:${i}`)),
    regroup: review.regroup.filter((r) => ticked.has(`regroup:${r.id}`)).map((r) => ({ id: r.id, to: r.to })),
    merge_groups: review.merge_groups.filter((_, i) => ticked.has(`merge:${i}`)).map((m) => ({ from: m.from, to: m.to })),
  }
}
