// DayHeading: a quiet date heading between Feed rows ("Today", "Yesterday", "Tuesday 10 November")
// with how many items fall on that day. It is a row of the list, not an item: it takes no focus and
// the j / k keys step over it.
import type { DayEntry } from './dayGroups'

/** One date heading row. The count is left out while more pages could still add to the day. */
export function DayHeading({ entry }: { entry: DayEntry }) {
  return (
    <li className="r-feed-day">
      <h2 className="r-feed-day__title">{entry.label}</h2>
      {entry.count !== null && (
        <span className="r-feed-day__count">
          {entry.count} {entry.count === 1 ? 'item' : 'items'}
        </span>
      )}
    </li>
  )
}
