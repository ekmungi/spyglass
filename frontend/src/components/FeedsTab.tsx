// Feeds tab: add-by-URL bar + list of managed feeds + import/export bar.
import type { FeedData } from '../lib/types'
import { AddFeedBar } from './AddFeedBar'
import { FeedList } from './FeedList'
import { ImportExportBar } from './ImportExportBar'

interface Props {
  feeds: FeedData[]
  onUpdate: (id: number, patch: { enabled?: boolean; name?: string }) => void
  onDelete: (id: number) => void
  onRefresh: () => void
}

/** Feeds management tab: add-by-URL bar, feed list, and import/export controls. */
export function FeedsTab({ feeds, onUpdate, onDelete, onRefresh }: Props) {
  return (
    // Pinned add-by-URL bar on top; the feed list + import/export scroll below it.
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-none">
        <AddFeedBar onRefresh={onRefresh} />
      </div>
      <div className="tab-scroll">
        {feeds.length === 0 ? (
          <p className="text-muted">No feeds yet. Import an OPML file to get started.</p>
        ) : (
          <FeedList feeds={feeds} onUpdate={onUpdate} onDelete={onDelete} />
        )}
        <ImportExportBar onRefresh={onRefresh} />
      </div>
    </div>
  )
}
