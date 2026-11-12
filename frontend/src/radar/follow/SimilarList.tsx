// SimilarList: items already in the feed that resemble the one being read, as quiet links to the reader.
import type { RadarItem } from '../api/types'
import { ItemLink } from '../components/ItemLink'
import { plainText } from '../lib/plainText'

/** Most items shown under the checklist. */
export const SIMILAR_LIMIT = 8

/** "Similar in your feed": up to eight links; renders nothing for an empty list. */
export function SimilarList({ items, onOpen }: { items: readonly RadarItem[]; onOpen: () => void }) {
  if (items.length === 0) return null
  return (
    <section aria-labelledby="rf-similar-title" className="rf-similar">
      <h3 id="rf-similar-title" className="rf-sub">
        Similar in your feed
      </h3>
      <ul className="rf-similar__list">
        {items.slice(0, SIMILAR_LIMIT).map((item) => (
          <li key={item.id}>
            <ItemLink id={item.id} onOpen={onOpen}>
              {plainText(item.headline) || plainText(item.title)}
            </ItemLink>
            <span className="r-meta"> {item.origin}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
