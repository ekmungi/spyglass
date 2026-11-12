// Shapes for the Watch page's group actions and AI review (PATCH /watch/groups, POST /watch/groups/restore,
// POST /watch/review, POST /watch/review/apply). The register itself is in pageTypes.ts.
import type { WatchEntity, WatchKind, WatchResponse } from './pageTypes'

export type WatchGroupAction = 'pause' | 'resume' | 'rename' | 'move' | 'remove'

export interface WatchGroupBody {
  category: string
  action: WatchGroupAction
  /** The new name, for rename and move. */
  to?: string
}

/** An entry as removed with its group: everything needed to put it back. */
export interface RemovedWatchEntity extends WatchEntity {
  links: { item_id: number; via: string }[]
}

/** The fresh register plus the entries a "remove" took out (empty for the other actions). */
export interface WatchGroupResponse extends WatchResponse {
  removed: RemovedWatchEntity[]
}

export interface WatchRestoreResponse extends WatchResponse {
  restored: number
}

export type ReviewMode = 'ai' | 'basic'

/** A name proposed for pausing or removing. */
export interface ReviewNameProposal {
  id: number
  name: string
  category: string
  reason: string
}

/** An organisation proposed for adding. */
export interface ReviewAddProposal {
  name: string
  kind: WatchKind | (string & {})
  category: string
  why: string
  query: string
}

export interface ReviewRegroupProposal {
  id: number
  name: string
  from: string
  to: string
  reason: string
}

export interface ReviewMergeProposal {
  from: string
  to: string
  reason: string
  /** How many names are in the group being merged away. */
  count: number
}

/** POST /watch/review: nothing has been changed yet. */
export interface WatchReview {
  mode: ReviewMode
  /** Why this is the basic review although an AI one was wanted, or that no model is set up. */
  note?: string
  summary: string
  pause: ReviewNameProposal[]
  remove: ReviewNameProposal[]
  add: ReviewAddProposal[]
  regroup: ReviewRegroupProposal[]
  merge_groups: ReviewMergeProposal[]
}

/** POST /watch/review/apply: exactly what the reader ticked. */
export interface WatchApplyBody {
  pause: number[]
  remove: number[]
  add: ReviewAddProposal[]
  regroup: { id: number; to: string }[]
  merge_groups: { from: string; to: string }[]
}

export interface WatchApplyCounts {
  paused: number
  removed: number
  added: number
  regrouped: number
  merged: number
}

export interface WatchApplyResponse extends WatchResponse {
  applied: WatchApplyCounts
  /** The removed entries, for Undo. */
  removed: RemovedWatchEntity[]
}
