// TrackRow: one followed topic: its name (a link to the Feed searched for it), its section, when
// it was last checked and how many items it found, its latest items, and a menu.
import type { Track } from '../../api/types'
import { plainText } from '../../lib/plainText'
import { buildHash } from '../../router'
import { IconButton, IconMore, Menu, type MenuItem } from '../../ui'
import { formatDay } from '../sources/format'
import { checkedLine } from './checkedLine'

export interface TrackRowProps {
  track: Track
  busy: boolean
  menu: MenuItem[]
}

/** A row in the "Topics you follow" group. */
export function TrackRow({ track, busy, menu }: TrackRowProps) {
  const recent = track.recent ?? []
  return (
    <li className="rw-row" aria-busy={busy || undefined}>
      <div className="rw-main">
        <div className="rw-line">
          <a className="r-headline rw-name rw-track-name" href={buildHash({ name: 'feed', params: { q: track.label } })} title="Search the Feed for this topic">
            {track.label}
          </a>
          {track.section_label && <span className="r-meta">{track.section_label}</span>}
          {!track.active && <span className="r-meta">Paused</span>}
        </div>
        <p className="rw-why">{checkedLine(track)}</p>
        {recent.length > 0 && (
          <ul className="rw-recent" aria-label={`Latest for ${track.label}`}>
            {recent.slice(0, 3).map((item) => (
              <li key={item.id}>
                <a href={`#/item/${item.id}`}>{plainText(item.headline) || plainText(item.title)}</a>
                {(item.published_at || item.fetched_at) && <span className="r-meta"> {formatDay(item.published_at ?? item.fetched_at)}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="rw-actions">
        <Menu
          label={`Actions for ${track.label}`}
          items={menu}
          trigger={<IconButton label={`Actions for ${track.label}`} icon={<IconMore size={16} />} size="sm" disabled={busy} />}
        />
      </div>
    </li>
  )
}
