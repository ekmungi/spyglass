// Sources page: where Spyglass gets its material. A header line (last collection, next brief,
// Collect now), then one strip of tabs: what the reader sends in, the feeds, the automatic searches
// and the FDA device decisions. Only the selected group is shown.
import './sources/sources.css'
import { useState } from 'react'
import { Button, Skeleton, Tabs, type TabItem } from '../ui'
import { loadSources, loadStatus, type FeedRow, type SourcesView, type StatusView } from './sources/api'
import { CollectBar } from './sources/CollectBar'
import { FdaSection } from './sources/FdaSection'
import { failingAlert } from './sources/feedHealth'
import { FeedsSection } from './sources/FeedsSection'
import { FromYou } from './sources/FromYou'
import { SignalsSection } from './sources/SignalsSection'
import { signalRows } from './sources/signalRows'
import { useLoad } from './sources/useLoad'

type SourcesTab = 'from-you' | 'feeds' | 'signals' | 'fda'

/** The Sources page (no props). */
export default function SourcesPage() {
  const sources = useLoad<SourcesView>((signal) => loadSources(signal), 'sources')
  const status = useLoad<StatusView>((signal) => loadStatus(signal), 'sources-status')
  const view = sources.data
  const [selected, setSelected] = useState<SourcesTab>('from-you')

  // "Searches" is left out when the server reports no such collector, so the strip never opens an empty tab.
  const tabs: TabItem[] = view
    ? [
        { key: 'from-you', label: 'From you' },
        { key: 'feeds', label: 'Feeds', alert: failingAlert(view.feeds) },
        ...(signalRows(view.collectors).length > 0 ? [{ key: 'signals', label: 'Searches' }] : []),
        { key: 'fda', label: 'FDA decisions' },
      ]
    : []
  const tab = tabs.some((entry) => entry.key === selected) ? selected : 'from-you'

  const setFeeds = (feeds: FeedRow[]) => {
    if (view) sources.replace({ ...view, feeds })
  }

  return (
    <div className="r-page r-page--wide">
      <h1 className="r-page-title">Sources</h1>
      <p className="r-page-meta">Where your material comes from, and whether each source is working.</p>

      <CollectBar
        status={status.data}
        onStatus={status.replace}
        onFinished={() => {
          sources.reload()
          status.reload()
        }}
      />
      {status.error && !status.data && <p className="r-meta">The collection status could not be read. {status.error}</p>}

      {sources.loading && !view && (
        <div aria-busy="true" aria-label="Loading your sources" className="rs-skeleton">
          <Skeleton width="25%" height={14} />
          <Skeleton lines={3} />
          <Skeleton width="25%" height={14} />
          <Skeleton lines={4} />
        </div>
      )}

      {sources.error && (
        <div className="rs-error" role="alert">
          <p className="r-error-text">{view ? `Could not refresh the sources. ${sources.error}` : sources.error}</p>
          <Button onClick={sources.reload}>Try again</Button>
        </div>
      )}

      {view && (
        <>
          <Tabs label="Sources" tabs={tabs} value={tab} onChange={(key) => setSelected(key as SourcesTab)} />
          <div role="tabpanel" className="rs-panel">
            {tab === 'from-you' && <FromYou collectors={view.collectors} />}
            {tab === 'feeds' && <FeedsSection feeds={view.feeds} onChange={setFeeds} />}
            {tab === 'signals' && <SignalsSection collectors={view.collectors} />}
            {tab === 'fda' && <FdaSection collectors={view.collectors} />}
          </div>
        </>
      )}
    </div>
  )
}
