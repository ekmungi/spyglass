// FeedsSection: the feeds that need a look, one line of counts that stands in for the feeds that work (with
// a button to list them), and the add form. Each feed has its health in words, an on/off switch and removal.
// A feed the reader switches during this visit stays in the list it was in, with the focus, until the
// reader folds or unfolds the working feeds.
import { useCallback, useState } from 'react'
import { errorMessage } from '../../api/errors'
import { useStayListed } from '../../hooks/useStayListed'
import { Button, Dialog, EmptyState, SectionHeading, toast } from '../../ui'
import { removeFeed, setFeedEnabled, type FeedRow } from './api'
import { AddFeed } from './AddFeed'
import { FeedRowItem } from './FeedRowItem'
import { feedGroup, otherFeedsSummary, placeFeeds, splitFeeds, type FeedGroup } from './feedHealth'

export interface FeedsSectionProps {
  feeds: readonly FeedRow[]
  /** Replace the feed list (after an add, a switch or a removal). */
  onChange: (feeds: FeedRow[]) => void
}

/** The "Feeds" group. Changes are applied to the list at once once the server has confirmed them. */
export function FeedsSection({ feeds, onChange }: FeedsSectionProps) {
  const [busyId, setBusyId] = useState<number | null>(null)
  const [removing, setRemoving] = useState<FeedRow | null>(null)
  const [showWorking, setShowWorking] = useState(false)
  const changed = useStayListed<number, FeedGroup>()
  // The counts describe each feed's state now; the lists keep a feed switched during this visit in place.
  const counted = splitFeeds(feeds)
  const { working, others } = placeFeeds(feeds, changed.pinned)

  // A stable handler: the dialog refocuses its first control whenever this function changes.
  const closeRemove = useCallback(() => setRemoving(null), [])

  const toggle = async (feed: FeedRow, enabled: boolean) => {
    setBusyId(feed.id)
    changed.pin(feed.id, feedGroup(feed))
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
        <>
          {others.length > 0 && (
            <ul className="r-rows">
              {others.map((feed) => (
                <FeedRowItem key={feed.id} feed={feed} busy={busyId === feed.id} onToggle={(row, enabled) => void toggle(row, enabled)} onRemove={setRemoving} />
              ))}
            </ul>
          )}
          <div className="rs-feedline">
            <span className="r-meta">
              {[otherFeedsSummary(counted.others), counted.working.length > 0 ? `${counted.working.length} working` : ''].filter(Boolean).join('. ')}.
            </span>
            {working.length > 0 && (
              <Button
                variant="quiet"
                size="sm"
                aria-expanded={showWorking}
                onClick={() => {
                  setShowWorking((shown) => !shown)
                  changed.release()
                }}
              >
                {showWorking ? 'Hide the working feeds' : 'Show the working feeds'}
              </Button>
            )}
          </div>
          {showWorking && working.length > 0 && (
            <ul className="r-rows">
              {working.map((feed) => (
                <FeedRowItem key={feed.id} feed={feed} busy={busyId === feed.id} onToggle={(row, enabled) => void toggle(row, enabled)} onRemove={setRemoving} />
              ))}
            </ul>
          )}
        </>
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
