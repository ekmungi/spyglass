// FeedToolbar: the Feed's sticky bar. One row with the search field, a thin line, the Ask button and
// the Filters menu; under it the views strip (Everything, Missed, Saved, From you, To file) and the
// sections strip. The page measures the bar's height so the pinned day heading sits right under it.
import { forwardRef } from 'react'
import { focusComposer, setAssistTarget } from '../assistant/assistStore'
import { IconAsk, IconButton, IconFilter, IconSearch, Menu, Tabs, type MenuItem, type TabItem } from '../ui'
import type { FeedView } from './feedViews'

/** The key of the "All sections" tab; no real section has this key. */
const ALL_SECTIONS = 'all'

export interface FeedToolbarProps {
  search: string
  onSearch: (value: string) => void
  filterItems: MenuItem[]
  /** How many of the menu's own filters are on; shown after the button's name. */
  filterCount: number
  view: FeedView
  onView: (view: FeedView) => void
  /** Filing is set up, so the To file view exists. */
  filingOn: boolean
  missedCount: number
  filingCount: number | null
  sections: { key: string; label: string }[]
  /** The key of the chosen section, or undefined for all of them. */
  section: string | undefined
  onSection: (key: string | null) => void
}

/** The toolbar; the ref goes to the outer box so the page can measure its height. */
export const FeedToolbar = forwardRef<HTMLDivElement, FeedToolbarProps>(function FeedToolbar(props, ref) {
  const { search, onSearch, filterItems, filterCount, view, onView, filingOn, missedCount, filingCount, sections, section, onSection } = props
  const views: TabItem[] = [
    { key: 'everything', label: 'Everything' },
    { key: 'missed', label: 'Missed', count: missedCount || undefined },
    { key: 'saved', label: 'Saved' },
    { key: 'from_you', label: 'From you' },
    ...(filingOn ? [{ key: 'to_file', label: 'To file', count: filingCount || undefined }] : []),
  ]
  const sectionTabs: TabItem[] = [{ key: ALL_SECTIONS, label: 'All sections' }, ...sections.map(({ key, label }) => ({ key, label }))]
  return (
    <div className="r-feed-filters" ref={ref}>
      <div className="r-feed-filters__top">
        <label className="r-feed-search">
          <IconSearch size={16} />
          <span className="r-sr-only">Search the feed</span>
          <input type="search" value={search} placeholder="Search titles, summaries and full text" onChange={(event) => onSearch(event.target.value)} />
        </label>
        <span className="r-feed-filters__gap" aria-hidden="true" />
        {/* The filter bar stays in view while the list scrolls, so this is always within reach. */}
        <IconButton
          label="Ask your feed (opens the assistant)"
          icon={<IconAsk size={18} />}
          tooltipSide="bottom"
          onClick={() => {
            setAssistTarget({ kind: 'feed' })
            focusComposer('feed')
          }}
        />
        <Menu
          label="More filters"
          items={filterItems}
          trigger={<IconButton label={filterCount ? `Filters (${filterCount})` : 'Filters'} icon={<IconFilter size={18} />} tooltipSide="bottom" />}
        />
      </div>
      <Tabs label="Views" tabs={views} value={view} onChange={(key) => onView(key as FeedView)} />
      <Tabs
        label="Sections"
        quiet
        tabs={sectionTabs}
        value={section ?? ALL_SECTIONS}
        onChange={(key) => onSection(key === ALL_SECTIONS ? null : key)}
      />
    </div>
  )
})
