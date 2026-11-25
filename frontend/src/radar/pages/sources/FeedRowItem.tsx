// FeedRowItem: one subscribed feed with its health in words, a mark when it is failing, an on/off
// switch, and the actions menu.
import { IconAlert, IconButton, IconMore, Menu } from '../../ui'
import type { FeedRow } from './api'
import { feedStatus } from './describe'
import { formatWhen } from './format'
import { Switch } from './Switch'

export interface FeedRowItemProps {
  feed: FeedRow
  /** True while a change to this feed is on its way to the server. */
  busy: boolean
  onToggle: (feed: FeedRow, enabled: boolean) => void
  onRemove: (feed: FeedRow) => void
}

/** One row of the feeds list. A failing feed carries a red alert mark before its name. */
export function FeedRowItem({ feed, busy, onToggle, onRemove }: FeedRowItemProps) {
  const status = feedStatus(feed)
  return (
    <li className="rs-row" aria-busy={busy || undefined}>
      <div className="rs-main">
        <div className="rs-line">
          <span className="rs-name">
            {status.tone === 'problem' && (
              <span className="rs-alert">
                <IconAlert size={14} label="This feed is failing" />
              </span>
            )}
            {feed.name}
          </span>
          <span className={status.tone === 'problem' ? 'rs-problem' : status.tone === 'ok' ? 'rs-ok' : 'r-meta'}>
            {status.tone === 'problem' ? 'Failing' : status.text}
          </span>
        </div>
        {status.tone === 'problem' && <p className="rs-problem">{status.text}</p>}
        <p className="r-meta">
          {[feed.lastFetchAt ? `Fetched ${formatWhen(feed.lastFetchAt)}` : null, feed.items !== null ? `${feed.items} items` : null]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </div>
      <div className="rs-actions">
        <Switch label={`${feed.name} on or off`} checked={feed.enabled} disabled={busy} onChange={(next) => onToggle(feed, next)} />
        <Menu
          label={`Actions for ${feed.name}`}
          items={[{ id: 'remove', label: 'Remove…', onSelect: () => onRemove(feed) }]}
          trigger={<IconButton label={`Actions for ${feed.name}`} icon={<IconMore size={16} />} size="sm" />}
        />
      </div>
    </li>
  )
}
