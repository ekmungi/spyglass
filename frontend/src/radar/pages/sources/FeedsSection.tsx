// FeedsSection: every subscribed feed with its health in words, an on/off switch, removal, and the add form.
import { useCallback, useState } from 'react'
import { errorMessage } from '../../api/errors'
import { Button, Dialog, EmptyState, IconButton, IconMore, Menu, SectionHeading, toast } from '../../ui'
import { removeFeed, setFeedEnabled, type FeedRow } from './api'
import { AddFeed } from './AddFeed'
import { feedStatus } from './describe'
import { formatWhen } from './format'
import { Switch } from './Switch'

export interface FeedsSectionProps {
  feeds: readonly FeedRow[]
  /** Replace the feed list (after an add, a switch or a removal). */
  onChange: (feeds: FeedRow[]) => void
}

/** The "Feeds" group. Changes are applied to the list at once once the server has confirmed them. */
export function FeedsSection({ feeds, onChange }: FeedsSectionProps) {
  const [busyId, setBusyId] = useState<number | null>(null)
  const [removing, setRemoving] = useState<FeedRow | null>(null)

  // A stable handler: the dialog refocuses its first control whenever this function changes.
  const closeRemove = useCallback(() => setRemoving(null), [])

  const toggle = async (feed: FeedRow, enabled: boolean) => {
    setBusyId(feed.id)
    try {
      await setFeedEnabled(feed.id, enabled)
      onChange(feeds.map((row) => (row.id === feed.id ? { ...row, enabled } : row)))
    } catch (cause) {
      toast(errorMessage(cause), { tone: 'error' })
    } finally {
      setBusyId(null)
    }
  }

  const confirmRemove = async () => {
    if (!removing) return
    const feed = removing
    setBusyId(feed.id)
    try {
      await removeFeed(feed.id)
      onChange(feeds.filter((row) => row.id !== feed.id))
      setRemoving(null)
      toast(`Removed ${feed.name}`)
    } catch (cause) {
      toast(errorMessage(cause), { tone: 'error' })
    } finally {
      setBusyId(null)
    }
  }

  const add = (feed: FeedRow) => onChange([...feeds.filter((row) => row.id !== feed.id), feed].sort((a, b) => a.name.localeCompare(b.name)))

  return (
    <section aria-labelledby="sources-feeds" className="rs-section">
      <SectionHeading id="sources-feeds" note={feeds.length > 0 ? `${feeds.length}` : undefined}>
        Feeds
      </SectionHeading>
      {feeds.length === 0 ? (
        <EmptyState title="No feeds yet" body="Add the address of a blog, newsletter or journal feed below and Spyglass checks it for new items." />
      ) : (
        <ul className="r-rows">
          {feeds.map((feed) => {
            const status = feedStatus(feed)
            return (
              <li key={feed.id} className="rs-row" aria-busy={busyId === feed.id || undefined}>
                <div className="rs-main">
                  <div className="rs-line">
                    <span className="rs-name">{feed.name}</span>
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
                  <Switch label={`${feed.name} on or off`} checked={feed.enabled} disabled={busyId === feed.id} onChange={(next) => void toggle(feed, next)} />
                  <Menu
                    label={`Actions for ${feed.name}`}
                    items={[{ id: 'remove', label: 'Remove…', onSelect: () => setRemoving(feed) }]}
                    trigger={<IconButton label={`Actions for ${feed.name}`} icon={<IconMore size={16} />} size="sm" />}
                  />
                </div>
              </li>
            )
          })}
        </ul>
      )}
      <AddFeed onAdded={add} />
      <Dialog
        open={removing !== null}
        onClose={closeRemove}
        title={removing ? `Remove ${removing.name}?` : 'Remove'}
        footer={
          <>
            <Button variant="quiet" onClick={closeRemove}>
              Cancel
            </Button>
            <Button variant="primary" disabled={busyId !== null} onClick={() => void confirmRemove()}>
              Remove feed
            </Button>
          </>
        }
      >
        <p className="r-meta">The feed and every item it collected are deleted from Spyglass. This cannot be undone.</p>
      </Dialog>
    </section>
  )
}
