// Feed list: table of all managed feeds, one FeedRow per entry.
import type { FeedData } from '../lib/types'
import { FeedRow } from './FeedRow'

interface Props {
  feeds: FeedData[]
  onUpdate: (id: number, patch: { enabled?: boolean; name?: string }) => void
  onDelete: (id: number) => void
}

/** Sortable table of all managed feeds. */
export function FeedList({ feeds, onUpdate, onDelete }: Props) {
  return (
    <table className="w-full text-left" style={{ fontSize: 'var(--font-size-body)' }}>
      <thead>
        <tr className="border-b border-border text-muted">
          <th className="py-2 pr-4 font-semibold">Name</th>
          <th className="py-2 pr-4 font-semibold">URL</th>
          <th className="py-2 pr-4 font-semibold">Status</th>
          <th className="py-2 pr-4 font-semibold">Items</th>
          <th className="py-2 pr-4 font-semibold">Enabled</th>
          <th className="py-2 font-semibold">Actions</th>
        </tr>
      </thead>
      <tbody>
        {feeds.map((feed) => (
          <FeedRow key={feed.id} feed={feed} onUpdate={onUpdate} onDelete={onDelete} />
        ))}
      </tbody>
    </table>
  )
}
