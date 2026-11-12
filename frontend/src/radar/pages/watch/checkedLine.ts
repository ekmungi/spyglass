// checkedLine: the quiet "Last checked 5 h ago · 2 new" line under a followed topic.
import type { Track } from '../../api/types'
import { relativeTime } from '../../lib/format'

/** "Last checked 5 h ago · 2 new", or "Not checked yet" before its first search. */
export function checkedLine(track: Pick<Track, 'last_run_at' | 'last_new'>, now: Date = new Date()): string {
  if (!track.last_run_at) return 'Not checked yet'
  const when = relativeTime(track.last_run_at, now)
  return `Last checked ${when} · ${track.last_new > 0 ? `${track.last_new} new` : 'nothing new'}`
}
