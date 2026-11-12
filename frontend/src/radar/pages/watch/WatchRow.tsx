// WatchRow: one name in the register (or one suggestion): what it is, why it is followed, and its latest items.
import type { ReactNode } from 'react'
import { plainText } from '../../lib/plainText'
import { IconButton, IconMore, Menu, type MenuItem } from '../../ui'
import { formatDay } from '../sources/format'
import type { WatchEntry } from './api'
import { kindLabel } from './kind'
import { hasRecentHit } from './organize'

export interface WatchRowProps {
  entry: WatchEntry
  busy: boolean
  /** Menu actions for a followed name; a suggestion passes `actions` instead. */
  menu?: MenuItem[]
  /** Buttons shown at the right, used by suggestions (Accept, Dismiss). */
  actions?: ReactNode
}

/** A register row: name, kind, one-line why, and up to three recent items as quiet links to the reader. */
export function WatchRow({ entry, busy, menu, actions }: WatchRowProps) {
  const recent = entry.recent ?? []
  const hit = hasRecentHit(entry)
  return (
    <li className="rw-row" aria-busy={busy || undefined}>
      <div className="rw-main">
        <div className="rw-line">
          <span className="r-headline rw-name">{entry.name}</span>
          <span className="r-meta">{kindLabel(entry.kind)}</span>
          {entry.status === 'muted' && <span className="r-meta">Muted</span>}
          {hit && <span className="rw-hit">Last mentioned {formatDay(entry.last_hit_at)}</span>}
        </div>
        {entry.why && <p className="rw-why">{entry.why}</p>}
        {entry.status === 'suggested' && entry.topic && <p className="r-meta">Suggested for {entry.topic}</p>}
        {recent.length > 0 && (
          <ul className="rw-recent" aria-label={`Latest from ${entry.name}`}>
            {recent.slice(0, 3).map((item) => (
              <li key={item.id}>
                <a href={`#/item/${item.id}`}>{plainText(item.headline) || plainText(item.title)}</a>
                {(item.published_at || item.fetched_at) && (
                  <span className="r-meta"> {formatDay(item.published_at ?? item.fetched_at)}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="rw-actions">
        {actions}
        {menu && (
          <Menu
            label={`Actions for ${entry.name}`}
            items={menu}
            trigger={<IconButton label={`Actions for ${entry.name}`} icon={<IconMore size={16} />} size="sm" disabled={busy} />}
          />
        )}
      </div>
    </li>
  )
}
