// Sources page: where Spyglass gets its material. A header line (last collection, next brief,
// Collect now), then what the reader sends in, the feeds, and the automatic searches.
import './sources/sources.css'
import { Button, Skeleton } from '../ui'
import { loadSources, loadStatus, type FeedRow, type SourcesView, type StatusView } from './sources/api'
import { CollectBar } from './sources/CollectBar'
import { FdaSection } from './sources/FdaSection'
import { FeedsSection } from './sources/FeedsSection'
import { FromYou } from './sources/FromYou'
import { SignalsSection } from './sources/SignalsSection'
import { useLoad } from './sources/useLoad'

/** The Sources page (no props). */
export default function SourcesPage() {
  const sources = useLoad<SourcesView>((signal) => loadSources(signal), 'sources')
  const status = useLoad<StatusView>((signal) => loadStatus(signal), 'sources-status')
  const view = sources.data

  const setFeeds = (feeds: FeedRow[]) => {
    if (view) sources.replace({ ...view, feeds })
  }

  return (
    <div className="r-page">
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
          <FromYou collectors={view.collectors} />
          <FeedsSection feeds={view.feeds} onChange={setFeeds} />
          <SignalsSection collectors={view.collectors} />
          <FdaSection collectors={view.collectors} />
        </>
      )}
    </div>
  )
}
